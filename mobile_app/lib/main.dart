import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:camera/camera.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const EyeGuardApp());
}

class EyeGuardApp extends StatelessWidget {
  const EyeGuardApp({super.key});

  @override
  Widget build(BuildContext context) {
    final ColorScheme scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF1A8F7A),
      brightness: Brightness.dark,
    );

    return MaterialApp(
      title: 'EyeGuard Local',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        colorScheme: scheme,
        scaffoldBackgroundColor: const Color(0xFF050A18),
      ),
      home: const AuthScreen(),
    );
  }
}

class LocalDriverProfile {
  const LocalDriverProfile({
    required this.fullName,
    required this.documentNumber,
    required this.documentIssueDate,
    required this.vehiclePlate,
    required this.passwordHash,
    required this.createdAt,
    this.fatigueIndex = 100,
  });

  final String fullName;
  final String documentNumber;
  final String documentIssueDate;
  final String vehiclePlate;
  final String passwordHash;
  final String createdAt;
  final int fatigueIndex;

  LocalDriverProfile copyWith({int? fatigueIndex}) {
    return LocalDriverProfile(
      fullName: fullName,
      documentNumber: documentNumber,
      documentIssueDate: documentIssueDate,
      vehiclePlate: vehiclePlate,
      passwordHash: passwordHash,
      createdAt: createdAt,
      fatigueIndex: fatigueIndex ?? this.fatigueIndex,
    );
  }

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'fullName': fullName,
      'documentNumber': documentNumber,
      'documentIssueDate': documentIssueDate,
      'vehiclePlate': vehiclePlate,
      'passwordHash': passwordHash,
      'createdAt': createdAt,
      'fatigueIndex': fatigueIndex,
    };
  }

  static LocalDriverProfile fromJson(Map<String, dynamic> json) {
    return LocalDriverProfile(
      fullName: json['fullName'] as String? ?? '',
      documentNumber: json['documentNumber'] as String? ?? '',
      documentIssueDate: json['documentIssueDate'] as String? ?? '',
      vehiclePlate: json['vehiclePlate'] as String? ?? '',
      passwordHash: json['passwordHash'] as String? ?? '',
      createdAt: json['createdAt'] as String? ?? DateTime.now().toIso8601String(),
      fatigueIndex: (json['fatigueIndex'] as num?)?.toInt() ?? 100,
    );
  }
}

class LocalAuthRepository {
  static const String _profileKey = 'local_driver_profile_v1';

  Future<LocalDriverProfile?> getProfile() async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    final String? raw = prefs.getString(_profileKey);
    if (raw == null || raw.isEmpty) {
      return null;
    }
    final Map<String, dynamic> json = jsonDecode(raw) as Map<String, dynamic>;
    return LocalDriverProfile.fromJson(json);
  }

  Future<void> saveProfile(LocalDriverProfile profile) async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setString(_profileKey, jsonEncode(profile.toJson()));
  }

  Future<void> updateFatigueIndex(int index) async {
    final LocalDriverProfile? profile = await getProfile();
    if (profile == null) {
      return;
    }
    await saveProfile(profile.copyWith(fatigueIndex: index));
  }

  Future<bool> register({
    required String fullName,
    required String documentNumber,
    required String documentIssueDate,
    required String vehiclePlate,
    required String password,
  }) async {
    final LocalDriverProfile profile = LocalDriverProfile(
      fullName: fullName,
      documentNumber: documentNumber,
      documentIssueDate: documentIssueDate,
      vehiclePlate: vehiclePlate.toUpperCase(),
      passwordHash: _hash(password),
      createdAt: DateTime.now().toIso8601String(),
      fatigueIndex: 100,
    );

    await saveProfile(profile);
    return true;
  }

  Future<LocalDriverProfile?> login({
    required String documentNumber,
    required String password,
  }) async {
    final LocalDriverProfile? profile = await getProfile();
    if (profile == null) {
      return null;
    }
    if (profile.documentNumber.trim() != documentNumber.trim()) {
      return null;
    }
    if (profile.passwordHash != _hash(password)) {
      return null;
    }
    return profile;
  }

  String _hash(String input) {
    return sha256.convert(utf8.encode(input)).toString();
  }
}

class MobileSyncClient {
  MobileSyncClient({required this.baseUrl});

  static const String _queueKey = 'mobile_sync_pending_v1';
  static const int _maxQueueItems = 300;

  final String baseUrl;
  bool _flushing = false;

  Uri get _syncUri {
    final String cleanBase = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return Uri.parse('$cleanBase/api/mobile/sync-status/');
  }

  Future<bool> enqueueAndFlush(Map<String, dynamic> payload) async {
    final List<Map<String, dynamic>> queue = await _loadQueue();
    queue.add(payload);
    if (queue.length > _maxQueueItems) {
      queue.removeRange(0, queue.length - _maxQueueItems);
    }
    await _saveQueue(queue);
    return flushQueue();
  }

  Future<bool> flushQueue() async {
    if (_flushing) {
      return false;
    }
    _flushing = true;
    bool sentAny = false;
    try {
      final List<Map<String, dynamic>> queue = await _loadQueue();
      if (queue.isEmpty) {
        return true;
      }

      int firstFailedIndex = -1;
      for (int i = 0; i < queue.length; i++) {
        final bool ok = await _post(queue[i]);
        if (!ok) {
          firstFailedIndex = i;
          break;
        }
        sentAny = true;
      }

      if (firstFailedIndex == -1) {
        await _saveQueue(<Map<String, dynamic>>[]);
      } else {
        await _saveQueue(queue.sublist(firstFailedIndex));
      }
      return sentAny;
    } finally {
      _flushing = false;
    }
  }

  Future<bool> _post(Map<String, dynamic> payload) async {
    try {
      final http.Response response = await http
          .post(
            _syncUri,
            headers: <String, String>{'Content-Type': 'application/json'},
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 5));
      final bool ok = response.statusCode >= 200 && response.statusCode < 300;
      if (!ok) {
        debugPrint('SYNC FAIL status=${response.statusCode} uri=$_syncUri body=${response.body}');
      }
      return ok;
    } catch (e) {
      debugPrint('SYNC EXCEPTION uri=$_syncUri error=$e');
      return false;
    }
  }

  Future<List<Map<String, dynamic>>> _loadQueue() async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    final String? raw = prefs.getString(_queueKey);
    if (raw == null || raw.isEmpty) {
      return <Map<String, dynamic>>[];
    }
    try {
      final List<dynamic> decoded = jsonDecode(raw) as List<dynamic>;
      return decoded.whereType<Map>().map((Map item) {
        return item.map((dynamic k, dynamic v) => MapEntry(k.toString(), v));
      }).toList();
    } catch (_) {
      return <Map<String, dynamic>>[];
    }
  }

  Future<void> _saveQueue(List<Map<String, dynamic>> queue) async {
    final SharedPreferences prefs = await SharedPreferences.getInstance();
    await prefs.setString(_queueKey, jsonEncode(queue));
  }
}

class BackendResolver {
  BackendResolver({required this.candidates});

  final List<String> candidates;

  Future<String?> resolveReachable() async {
    for (final String raw in candidates) {
      final String base = raw.trim();
      if (base.isEmpty) {
        continue;
      }
      if (await _isHealthy(base)) {
        return base;
      }
    }
    return null;
  }

  Future<bool> _isHealthy(String baseUrl) async {
    try {
      final String cleanBase = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
      final Uri uri = Uri.parse('$cleanBase/api/health');
      final http.Response response = await http.get(uri).timeout(const Duration(seconds: 3));
      return response.statusCode >= 200 && response.statusCode < 300;
    } catch (_) {
      return false;
    }
  }
}

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final LocalAuthRepository _repository = LocalAuthRepository();

  bool _loading = false;
  bool _showRegister = false;
  String _message = 'Inicia sesion local para monitorear';

  final TextEditingController _loginDocumentController = TextEditingController();
  final TextEditingController _loginPasswordController = TextEditingController();

  final TextEditingController _fullNameController = TextEditingController();
  final TextEditingController _registerDocumentController = TextEditingController();
  final TextEditingController _plateController = TextEditingController();
  final TextEditingController _registerPasswordController = TextEditingController();
  final TextEditingController _confirmPasswordController = TextEditingController();

  DateTime? _issueDate;

  Future<void> _pickIssueDate() async {
    final DateTime now = DateTime.now();
    final DateTime initialDate = _issueDate ?? DateTime(now.year - 2, now.month, now.day);

    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: initialDate,
      firstDate: DateTime(1970),
      lastDate: now,
    );

    if (picked != null) {
      setState(() {
        _issueDate = picked;
      });
    }
  }

  String _formatDate(DateTime date) {
    final String mm = date.month.toString().padLeft(2, '0');
    final String dd = date.day.toString().padLeft(2, '0');
    return '${date.year}-$mm-$dd';
  }

  Future<void> _register() async {
    final String fullName = _fullNameController.text.trim();
    final String document = _registerDocumentController.text.trim();
    final String plate = _plateController.text.trim().toUpperCase();
    final String password = _registerPasswordController.text;
    final String confirmPassword = _confirmPasswordController.text;

    if (fullName.isEmpty || document.isEmpty || plate.isEmpty || password.isEmpty) {
      setState(() {
        _message = 'Completa todos los campos del registro';
      });
      return;
    }

    if (_issueDate == null) {
      setState(() {
        _message = 'Selecciona la fecha de expedicion del documento';
      });
      return;
    }

    if (password.length < 6) {
      setState(() {
        _message = 'La contrasena debe tener minimo 6 caracteres';
      });
      return;
    }

    if (password != confirmPassword) {
      setState(() {
        _message = 'Las contrasenas no coinciden';
      });
      return;
    }

    setState(() {
      _loading = true;
      _message = 'Guardando registro local...';
    });

    await _repository.register(
      fullName: fullName,
      documentNumber: document,
      documentIssueDate: _formatDate(_issueDate!),
      vehiclePlate: plate,
      password: password,
    );

    if (!mounted) {
      return;
    }

    setState(() {
      _loading = false;
      _showRegister = false;
      _message = 'Registro creado localmente. Ya puedes iniciar sesion.';
      _loginDocumentController.text = document;
    });
  }

  Future<void> _login() async {
    final String document = _loginDocumentController.text.trim();
    final String password = _loginPasswordController.text;

    if (document.isEmpty || password.isEmpty) {
      setState(() {
        _message = 'Ingresa documento y contrasena';
      });
      return;
    }

    setState(() {
      _loading = true;
      _message = 'Validando credenciales locales...';
    });

    final LocalDriverProfile? profile = await _repository.login(
      documentNumber: document,
      password: password,
    );

    if (!mounted) {
      return;
    }

    if (profile == null) {
      setState(() {
        _loading = false;
        _message = 'Credenciales invalidas o no existe registro local';
      });
      return;
    }

    Navigator.of(context).pushReplacement(
      MaterialPageRoute<Widget>(
        builder: (_) => DetectionScreen(profile: profile, repository: _repository),
      ),
    );
  }

  @override
  void dispose() {
    _loginDocumentController.dispose();
    _loginPasswordController.dispose();
    _fullNameController.dispose();
    _registerDocumentController.dispose();
    _plateController.dispose();
    _registerPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Widget _glassCard({required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(20),
        gradient: LinearGradient(
          colors: <Color>[
            Colors.white.withAlpha(28),
            Colors.white.withAlpha(12),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        border: Border.all(color: Colors.white.withAlpha(35), width: 1),
        boxShadow: <BoxShadow>[
          BoxShadow(
            color: Colors.black.withAlpha(60),
            blurRadius: 30,
            offset: const Offset(0, 16),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: child,
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: <Widget>[
        Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            gradient: const LinearGradient(
              colors: <Color>[Color(0xFF22C55E), Color(0xFF7C3AED)],
            ),
          ),
          child: const Center(
            child: Text(
              'EG',
              style: TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
        ),
        const SizedBox(width: 12),
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                'EyeGuard',
                style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 2),
              Text('Monitoreo local de somnolencia'),
            ],
          ),
        ),
      ],
    );
  }

  InputDecoration _inputDecoration(String label) {
    return InputDecoration(
      labelText: label,
      filled: true,
      fillColor: Colors.black.withAlpha(25),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Color(0xFF22C55E), width: 1.4),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment.topLeft,
            radius: 1.2,
            colors: <Color>[Color(0xFF0A1C4A), Color(0xFF050A18), Color(0xFF03060E)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(18),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: _glassCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: <Widget>[
                      _buildHeader(),
                      const SizedBox(height: 18),
                      SegmentedButton<bool>(
                        segments: const <ButtonSegment<bool>>[
                          ButtonSegment<bool>(value: false, label: Text('Iniciar sesion')),
                          ButtonSegment<bool>(value: true, label: Text('Registro local')),
                        ],
                        selected: <bool>{_showRegister},
                        onSelectionChanged: (Set<bool> selection) {
                          setState(() {
                            _showRegister = selection.first;
                          });
                        },
                      ),
                      const SizedBox(height: 16),
                      if (_showRegister) ...<Widget>[
                        TextField(
                          controller: _fullNameController,
                          textCapitalization: TextCapitalization.words,
                          decoration: _inputDecoration('Nombre completo'),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: _registerDocumentController,
                          keyboardType: TextInputType.number,
                          decoration: _inputDecoration('Numero de documento'),
                        ),
                        const SizedBox(height: 10),
                        InkWell(
                          onTap: _pickIssueDate,
                          borderRadius: BorderRadius.circular(12),
                          child: InputDecorator(
                            decoration: _inputDecoration('Fecha de expedicion'),
                            child: Text(
                              _issueDate == null ? 'Seleccionar fecha' : _formatDate(_issueDate!),
                              style: TextStyle(
                                color: _issueDate == null ? Colors.white70 : Colors.white,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: _plateController,
                          textCapitalization: TextCapitalization.characters,
                          decoration: _inputDecoration('Placa del vehiculo'),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: _registerPasswordController,
                          obscureText: true,
                          decoration: _inputDecoration('Contrasena'),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: _confirmPasswordController,
                          obscureText: true,
                          decoration: _inputDecoration('Confirmar contrasena'),
                        ),
                        const SizedBox(height: 14),
                        FilledButton(
                          onPressed: _loading ? null : _register,
                          child: const Text('Crear perfil local'),
                        ),
                      ] else ...<Widget>[
                        TextField(
                          controller: _loginDocumentController,
                          keyboardType: TextInputType.number,
                          decoration: _inputDecoration('Numero de documento'),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: _loginPasswordController,
                          obscureText: true,
                          decoration: _inputDecoration('Contrasena'),
                        ),
                        const SizedBox(height: 14),
                        FilledButton(
                          onPressed: _loading ? null : _login,
                          child: const Text('Entrar a la aplicacion'),
                        ),
                      ],
                      const SizedBox(height: 14),
                      if (_loading) const LinearProgressIndicator(),
                      const SizedBox(height: 8),
                      Text(_message, style: const TextStyle(color: Colors.white70)),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class DetectionScreen extends StatefulWidget {
  const DetectionScreen({
    super.key,
    required this.profile,
    required this.repository,
  });

  final LocalDriverProfile profile;
  final LocalAuthRepository repository;

  @override
  State<DetectionScreen> createState() => _DetectionScreenState();
}

class _DetectionScreenState extends State<DetectionScreen> {
  static const String _backendBaseUrl = String.fromEnvironment(
    'EYEGUARD_BACKEND_URL',
    defaultValue: 'https://eyeguard-76mp.onrender.com',
  );
  static const String _backendCandidatesRaw = String.fromEnvironment(
    'EYEGUARD_BACKEND_URLS',
    defaultValue: 'https://eyeguard-76mp.onrender.com,http://10.0.2.2:8000,http://127.0.0.1:8000',
  );

  CameraController? _cameraController;
  FaceDetector? _faceDetector;
  Timer? _timer;
  Timer? _syncTimer;
  late AudioPlayer _audioPlayer;
  late MobileSyncClient _syncClient;

  bool _cameraReady = false;
  bool _monitoring = false;
  bool _processing = false;
  bool _syncing = false;
  bool _backendReady = false;
  bool _locationDeniedForever = false;

  int _fatigueIndex = 100;
  int _threshold = 60;
  int _intervalMilliseconds = 300;
  String _status = 'normal';
  String _message = 'Inicia monitoreo para comenzar deteccion local';
  DateTime? _lastUpdate;
  DateTime? _lastSuccessfulSync;
  DateTime? _lastLocationAt;
  bool _noFaceDetectedAlert = false;
  double? _lastLatitude;
  double? _lastLongitude;
  String _activeBackend = '';

  @override
  void initState() {
    super.initState();
    _audioPlayer = AudioPlayer();
    _fatigueIndex = widget.profile.fatigueIndex;
    _faceDetector = FaceDetector(
      options: FaceDetectorOptions(
        performanceMode: FaceDetectorMode.fast,
        enableClassification: true,
      ),
    );
    _initBackend();
    _initCamera();
  }

  Future<void> _initBackend() async {
    final List<String> candidates = <String>{
      _backendBaseUrl,
      ..._backendCandidatesRaw.split(',').map((String s) => s.trim()),
    }.where((String s) => s.isNotEmpty).toList();

    final BackendResolver resolver = BackendResolver(candidates: candidates);
    final String? resolved = await resolver.resolveReachable();
    final String selected = resolved ?? _backendBaseUrl;

    _syncClient = MobileSyncClient(baseUrl: selected);

    if (!mounted) {
      return;
    }
    setState(() {
      _backendReady = true;
      _activeBackend = selected;
      if (resolved == null) {
        _message = 'Backend no verificado aun. Operando offline y reintentando sync.';
      }
    });

    await _syncProfileSnapshot();
  }

  Future<void> _initCamera() async {
    try {
      final List<CameraDescription> cameras = await availableCameras();
      if (cameras.isEmpty) {
        setState(() {
          _message = 'No se encontro camara en este dispositivo';
        });
        return;
      }

      final CameraDescription selected = cameras.firstWhere(
        (CameraDescription c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );

      final CameraController controller = CameraController(
        selected,
        ResolutionPreset.medium,
        enableAudio: false,
      );

      await controller.initialize();

      if (!mounted) {
        await controller.dispose();
        return;
      }

      setState(() {
        _cameraController = controller;
        _cameraReady = true;
        _message = 'Camara lista. Todo se procesa localmente.';
      });
    } on CameraException catch (e) {
      setState(() {
        _message = 'Error de camara: ${e.description ?? e.code}';
      });
    } catch (e) {
      setState(() {
        _message = 'No se pudo iniciar camara: $e';
      });
    }
  }

  Future<void> _runLocalDetection() async {
    if (_processing || !_monitoring) {
      return;
    }

    final CameraController? controller = _cameraController;
    final FaceDetector? detector = _faceDetector;
    if (controller == null || detector == null || !controller.value.isInitialized) {
      return;
    }

    _processing = true;
    try {
      final XFile frame = await controller.takePicture();
      final InputImage inputImage = InputImage.fromFilePath(frame.path);
      final List<Face> faces = await detector.processImage(inputImage);

      int nextIndex = _fatigueIndex;
      String status = _status;
      bool noFaceAlert = false;

      if (faces.isEmpty) {
        nextIndex = (nextIndex - 8).clamp(0, 100);
        status = 'sin rostro';
        noFaceAlert = true;
      } else {
        final Face face = faces.first;
        final double? left = face.leftEyeOpenProbability;
        final double? right = face.rightEyeOpenProbability;

        double openLevel = 0.5;
        if (left != null && right != null) {
          openLevel = (left + right) / 2;
        } else if (left != null) {
          openLevel = left;
        } else if (right != null) {
          openLevel = right;
        }

        if (openLevel >= 0.65) {
          nextIndex = (nextIndex + 4).clamp(0, 100);
          status = 'normal';
        } else if (openLevel >= 0.45) {
          nextIndex = (nextIndex - 2).clamp(0, 100);
          status = 'atencion';
        } else if (openLevel >= 0.30) {
          nextIndex = (nextIndex - 6).clamp(0, 100);
          status = 'somnoliento';
        } else {
          nextIndex = (nextIndex - 12).clamp(0, 100);
          status = 'critico';
        }
      }

      await widget.repository.updateFatigueIndex(nextIndex);

      if (!mounted) {
        return;
      }

      setState(() {
        _fatigueIndex = nextIndex;
        _status = status;
        _noFaceDetectedAlert = noFaceAlert;
        _lastUpdate = DateTime.now();
        _message = 'Deteccion local actualizada';
      });

      if (_fatigueIndex < _threshold || noFaceAlert) {
        _playAlertSound();
      }

      try {
        final File f = File(frame.path);
        if (await f.exists()) {
          await f.delete();
        }
      } catch (_) {
        // no-op
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _message = 'Error en deteccion local: $e';
        });
      }
    } finally {
      _processing = false;
    }
  }

  void _startMonitoring() {
    if (!_cameraReady || _cameraController == null) {
      setState(() {
        _message = 'La camara aun no esta lista';
      });
      return;
    }

    _timer?.cancel();
    _timer = Timer.periodic(Duration(milliseconds: _intervalMilliseconds), (_) {
      _runLocalDetection();
    });
    _syncTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      _syncCurrentState();
    });

    setState(() {
      _monitoring = true;
      _message = 'Monitoreo local activo (deteccion cada ${_intervalMilliseconds / 1000}s, sync cada 5s)';
    });

    _runLocalDetection();
    _syncCurrentState();
  }

  void _stopMonitoring() {
    _timer?.cancel();
    _timer = null;
    _syncTimer?.cancel();
    _syncTimer = null;
    setState(() {
      _monitoring = false;
      _message = 'Monitoreo detenido';
    });
  }

  Future<Map<String, double>?> _resolveLocation() async {
    if (_locationDeniedForever) {
      return null;
    }

    if (_lastLocationAt != null &&
        _lastLatitude != null &&
        _lastLongitude != null &&
        DateTime.now().difference(_lastLocationAt!) < const Duration(seconds: 15)) {
      return <String, double>{
        'latitude': _lastLatitude!,
        'longitude': _lastLongitude!,
      };
    }

    try {
      final bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        return null;
      }

      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.deniedForever) {
        _locationDeniedForever = true;
        return null;
      }
      if (permission == LocationPermission.denied) {
        return null;
      }

      final Position position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 4),
        ),
      );

      _lastLatitude = position.latitude;
      _lastLongitude = position.longitude;
      _lastLocationAt = DateTime.now();

      return <String, double>{
        'latitude': position.latitude,
        'longitude': position.longitude,
      };
    } catch (_) {
      return null;
    }
  }

  Future<bool> _syncCurrentState({bool allowWhenStopped = false}) async {
    if (!_backendReady) {
      return false;
    }
    if (_syncing || (!allowWhenStopped && !_monitoring)) {
      return false;
    }

    _syncing = true;
    try {
      final Map<String, double>? loc = await _resolveLocation();
      final Map<String, dynamic> payload = <String, dynamic>{
        'fullName': widget.profile.fullName,
        'documentNumber': widget.profile.documentNumber,
        'documentIssueDate': widget.profile.documentIssueDate,
        'vehiclePlate': widget.profile.vehiclePlate,
        'fatigueIndex': _fatigueIndex,
        'status': _status,
        'faceDetected': !_noFaceDetectedAlert,
        'capturedAt': DateTime.now().toUtc().toIso8601String(),
      };
      if (loc != null) {
        payload['latitude'] = loc['latitude'];
        payload['longitude'] = loc['longitude'];
      }

      final bool sent = await _syncClient.enqueueAndFlush(payload);
      if (sent && mounted) {
        setState(() {
          _lastSuccessfulSync = DateTime.now();
        });
      }
      return sent;
    } finally {
      _syncing = false;
    }
  }

  Future<void> _syncProfileSnapshot() async {
    if (!_backendReady) {
      return;
    }
    final Map<String, dynamic> payload = <String, dynamic>{
      'fullName': widget.profile.fullName,
      'documentNumber': widget.profile.documentNumber,
      'documentIssueDate': widget.profile.documentIssueDate,
      'vehiclePlate': widget.profile.vehiclePlate,
      'fatigueIndex': _fatigueIndex,
      'status': _status,
      'faceDetected': !_noFaceDetectedAlert,
      'capturedAt': DateTime.now().toUtc().toIso8601String(),
      'source': 'mobile_local_profile',
    };
    final bool sent = await _syncClient.enqueueAndFlush(payload);
    if (sent && mounted) {
      setState(() {
        _lastSuccessfulSync = DateTime.now();
      });
    }
  }

  Future<void> _logout() async {
    _stopMonitoring();

    // Intenta un último respaldo a web (sin esperar mucho si no hay internet)
    setState(() {
      _message = 'Intentando respaldo final a web antes de cerrar sesion...';
    });

    try {
      bool sent = false;

      // 1) Encola y sincroniza un snapshot final aunque el monitoreo este detenido.
      sent = await _syncCurrentState(allowWhenStopped: true).timeout(
        const Duration(seconds: 3),
        onTimeout: () => false,
      );

      // 2) Si no envio, reintenta vaciar la cola pendiente.
      if (!sent) {
        sent = await _syncClient.flushQueue().timeout(
          const Duration(seconds: 3),
          onTimeout: () => false,
        );
      }

      if (mounted) {
        setState(() {
          if (sent) {
            _lastSuccessfulSync = DateTime.now();
            _message = 'Respaldo final enviado a web. Cerrando sesion...';
          } else {
            _message = 'Respaldo pendiente: sin conexion al backend. La app sigue offline.';
          }
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _message = 'Respaldo pendiente: sin conexion al backend. La app sigue offline.';
        });
      }
    }

    // Espera un momento para mostrar el mensaje
    await Future.delayed(const Duration(milliseconds: 800));

    if (mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute<Widget>(builder: (_) => const AuthScreen()),
        (Route<dynamic> route) => false,
      );
    }
  }

  void _playAlertSound() async {
    try {
      await _audioPlayer.setVolume(1.0);
      await _audioPlayer.play(UrlSource('https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3'));
    } catch (e) {
      debugPrint('Error reproduciendo sonido: $e');
    }

    try {
      SystemSound.play(SystemSoundType.alert);
    } catch (e) {
      debugPrint('Error reproduciendo SystemSound: $e');
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _syncTimer?.cancel();
    _cameraController?.dispose();
    _faceDetector?.close();
    _audioPlayer.dispose();
    super.dispose();
  }

  Widget _metricCard({required String label, required String value, Color? valueColor}) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          color: Colors.white.withAlpha(16),
          border: Border.all(color: Colors.white.withAlpha(24)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
            const SizedBox(height: 8),
            Text(
              value,
              style: TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 18,
                color: valueColor,
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bool inAlert = _fatigueIndex < _threshold || _noFaceDetectedAlert;
    final String alertReason = _noFaceDetectedAlert
        ? 'NO DETECTA CARA'
        : (_fatigueIndex < _threshold ? 'SOMNOLENCIA CRITICA' : '');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Deteccion Local de Somnolencia'),
        actions: <Widget>[
          IconButton(
            onPressed: _logout,
            icon: const Icon(Icons.logout),
            tooltip: 'Salir',
          ),
        ],
      ),
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: <Color>[Color(0xFF07112D), Color(0xFF03060E)],
          ),
        ),
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(16),
                    color: Colors.white.withAlpha(16),
                    border: Border.all(color: Colors.white.withAlpha(24)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        widget.profile.fullName,
                        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18),
                      ),
                      const SizedBox(height: 2),
                      Text('Doc: ${widget.profile.documentNumber} | Placa: ${widget.profile.vehiclePlate}'),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Expanded(
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(18),
                    child: _cameraReady && _cameraController != null
                        ? Stack(
                            fit: StackFit.expand,
                            children: <Widget>[
                              CameraPreview(_cameraController!),
                              if (inAlert)
                                Container(
                                  color: Colors.red.withAlpha(90),
                                  child: Center(
                                    child: Column(
                                      mainAxisAlignment: MainAxisAlignment.center,
                                      children: <Widget>[
                                        const Text(
                                          'ALERTA',
                                          style: TextStyle(
                                            fontWeight: FontWeight.w800,
                                            fontSize: 40,
                                            color: Colors.white,
                                          ),
                                        ),
                                        const SizedBox(height: 12),
                                        Text(
                                          alertReason,
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                            fontSize: 18,
                                            color: Colors.white,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ),
                            ],
                          )
                        : Container(
                            color: Colors.black,
                            child: const Center(child: Text('Inicializando camara...')),
                          ),
                  ),
                ),
                const SizedBox(height: 10),
                Row(
                  children: <Widget>[
                    _metricCard(
                      label: 'Indice',
                      value: '$_fatigueIndex',
                      valueColor: inAlert ? Colors.redAccent : Colors.greenAccent,
                    ),
                    const SizedBox(width: 8),
                    _metricCard(label: 'Estado', value: _status.toUpperCase()),
                  ],
                ),
                const SizedBox(height: 10),
                Text('Umbral de alerta: $_threshold'),
                Slider(
                  value: _threshold.toDouble(),
                  min: 40,
                  max: 90,
                  divisions: 10,
                  label: '$_threshold',
                  onChanged: (double value) {
                    setState(() {
                      _threshold = value.round();
                    });
                  },
                ),
                Row(
                  children: <Widget>[
                    ChoiceChip(
                      label: const Text('60'),
                      selected: _threshold == 60,
                      onSelected: (_) {
                        setState(() {
                          _threshold = 60;
                        });
                      },
                    ),
                    const SizedBox(width: 8),
                    ChoiceChip(
                      label: const Text('70'),
                      selected: _threshold == 70,
                      onSelected: (_) {
                        setState(() {
                          _threshold = 70;
                        });
                      },
                    ),
                    const Spacer(),
                    DropdownButton<int>(
                      value: _intervalMilliseconds,
                      items: const <DropdownMenuItem<int>>[
                        DropdownMenuItem<int>(value: 300, child: Text('0.3s')),
                        DropdownMenuItem<int>(value: 500, child: Text('0.5s')),
                        DropdownMenuItem<int>(value: 1000, child: Text('1s')),
                      ],
                      onChanged: (int? value) {
                        if (value == null) {
                          return;
                        }
                        final bool wasMonitoring = _monitoring;
                        _stopMonitoring();
                        setState(() {
                          _intervalMilliseconds = value;
                        });
                        if (wasMonitoring) {
                          _startMonitoring();
                        }
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: <Widget>[
                    FilledButton.icon(
                      onPressed: _monitoring ? null : _startMonitoring,
                      icon: const Icon(Icons.play_arrow),
                      label: const Text('Iniciar monitoreo'),
                    ),
                    OutlinedButton.icon(
                      onPressed: _monitoring ? _stopMonitoring : null,
                      icon: const Icon(Icons.stop),
                      label: const Text('Detener'),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(_message, style: const TextStyle(color: Colors.white70)),
                if (_lastUpdate != null)
                  Text('Ultima lectura: ${_lastUpdate!.toLocal()}', style: const TextStyle(color: Colors.white60)),
                if (_lastSuccessfulSync != null)
                  Text(
                    'Ultimo respaldo web: ${_lastSuccessfulSync!.toLocal()}',
                    style: const TextStyle(color: Colors.lightGreenAccent),
                  )
                else
                  const Text(
                    'Ultimo respaldo web: pendiente (app opera offline, sync al cerrar sesion)',
                    style: TextStyle(color: Colors.orangeAccent),
                  ),
                if (_activeBackend.isNotEmpty)
                  Text(
                    'Backend activo: $_activeBackend',
                    style: const TextStyle(color: Colors.white54),
                  ),
                if (_lastLatitude != null && _lastLongitude != null)
                  Text(
                    'Ubicacion: ${_lastLatitude!.toStringAsFixed(6)}, ${_lastLongitude!.toStringAsFixed(6)}',
                    style: const TextStyle(color: Colors.white60),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
