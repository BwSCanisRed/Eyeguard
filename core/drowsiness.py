import cv2
import numpy as np
import threading
import time
import math
from collections import deque
try:
    import mediapipe as mp
except Exception:
    mp = None

# Simple manager que mantiene un hilo por fuente de cámara (por conductor)
# y ofrece un frame MJPEG y un puntaje actual en memoria.

mp_face_mesh = None
if mp is not None:
    try:
        if hasattr(mp, 'solutions') and hasattr(mp.solutions, 'face_mesh'):
            mp_face_mesh = mp.solutions.face_mesh
        else:
            # Fallback para builds donde 'solutions' no viene expuesto en el root.
            from mediapipe.python.solutions import face_mesh as _face_mesh
            mp_face_mesh = _face_mesh
    except Exception:
        mp_face_mesh = None

_face_cascade = None
_eye_cascade = None
_warned_no_facemesh = False


def _create_face_mesh():
    global _warned_no_facemesh
    if mp_face_mesh is None:
        if not _warned_no_facemesh:
            print("[WARN] MediaPipe FaceMesh no disponible; usando fallback Haar para deteccion basica.")
            _warned_no_facemesh = True
        return None
    try:
        return mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    except Exception as e:
        print(f"[WARN] No se pudo crear FaceMesh: {e}")
        return None


def _ensure_haar_models():
    global _face_cascade, _eye_cascade
    if _face_cascade is not None and _eye_cascade is not None:
        return True
    try:
        face_xml = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        eye_xml = cv2.data.haarcascades + 'haarcascade_eye.xml'
        _face_cascade = cv2.CascadeClassifier(face_xml)
        _eye_cascade = cv2.CascadeClassifier(eye_xml)
        return not _face_cascade.empty() and not _eye_cascade.empty()
    except Exception:
        return False


def _detect_face_eyes_haar(frame, gray=None):
    """Fallback liviano: retorna (tiene_cara, ojos_detectados)."""
    if not _ensure_haar_models():
        return False, False
    try:
        if gray is None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
        if len(faces) == 0:
            return False, False
        # Usar la cara mas grande para estabilidad.
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        roi = gray[y:y + h, x:x + w]
        eyes = _eye_cascade.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=6, minSize=(18, 18))
        return True, len(eyes) >= 2
    except Exception:
        return False, False


def _resize_for_analysis(frame):
    h, w = frame.shape[:2]
    if w <= ANALYSIS_WIDTH:
        return frame
    target_h = max(1, int(h * (ANALYSIS_WIDTH / float(w))))
    return cv2.resize(frame, (ANALYSIS_WIDTH, target_h), interpolation=cv2.INTER_AREA)

LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]
NOSE_IDX = 1
CHIN_IDX = 152

# Parámetros mejorados para detección de somnolencia
FPS_SAVE = 5
ANALYSIS_WIDTH = 320
HAAR_RECHECK_INTERVAL = 3
MJPEG_ENCODE_INTERVAL = 0.08
EAR_THRESHOLD = 0.26
EAR_CONSEC_FRAMES = 1
MOUTH_OPEN_THRESHOLD = 0.22
HEAD_DOWN_THRESHOLD = 0.10
HEAD_NOD_THRESHOLD = 0.05
SCORE_START = 100
SCORE_MIN = 0
SCORE_MAX = 100
SCORE_DECREMENT_EYES_CLOSED = 6.0    # Ojos cerrados: caída rápida
SCORE_DECREMENT_NO_EYES = 4.0        # Sin ojos detectados
SCORE_INCREMENT_EYES_OPEN = 1.5      # Recuperación moderada
SCORE_DECREMENT_YAWN = 3.0
SCORE_DECREMENT_HEAD_DOWN = 8.0      # Cabeza inclinada: penalización fuerte
SCORE_DECREMENT_HEAD_NOD = 6.0       # Cabeceo: muy agresivo
SCORE_DECREMENT_NOD_EYES = 10.0      # Cabeceo + ojos cerrados: máxima penalización
SCORE_DECREMENT_NO_FACE = 2.0        # Sin cara detectada
ALERT_THRESHOLD = 50
ALERT_COOLDOWN = 3


class StreamState:
    def __init__(self, source):
        self.source = source
        self.lock = threading.Lock()
        self.frame = None
        self.score = SCORE_START
        self.last_alert = 0
        self.running = False
        self.thread = None

    @staticmethod
    def _calcular_dist(p1, p2):
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    @staticmethod
    def _calcular_EAR(eye_landmarks):
        try:
            p1, p2, p3, p4, p5, p6 = eye_landmarks
        except Exception:
            return 0.0
        A = StreamState._calcular_dist(p2, p6)
        B = StreamState._calcular_dist(p3, p5)
        C = StreamState._calcular_dist(p1, p4)
        if C == 0:
            return 0.0
        return (A + B) / (2.0 * C)

    def _process_loop(self):
        cap = cv2.VideoCapture(self.source)
        if not cap.isOpened():
            # try converting source to int
            try:
                cap = cv2.VideoCapture(int(self.source))
            except Exception:
                cap = None
        if not cap or not cap.isOpened():
            print(f"[drowsiness] no se pudo abrir fuente {self.source}")
            self.running = False
            return

        face_mesh = _create_face_mesh()

        frames_no_eyes = 0
        frames_eyes_closed = 0
        counter = 0

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb) if face_mesh else None

            ojos_detectados = False
            boca_detectada = False
            head_down = False
            ear = 0.0

            if results and results.multi_face_landmarks:
                face_landmarks = results.multi_face_landmarks[0]
                lm = face_landmarks.landmark
                pts = [(int(p.x * w), int(p.y * h)) for p in lm]
                # calcular EAR
                try:
                    left_eye_pts = [pts[idx] for idx in LEFT_EYE_IDX]
                    right_eye_pts = [pts[idx] for idx in RIGHT_EYE_IDX]
                    ear_left = StreamState._calcular_EAR(left_eye_pts)
                    ear_right = StreamState._calcular_EAR(right_eye_pts)
                    ear = (ear_left + ear_right) / 2.0
                    if ear > 0.01:
                        ojos_detectados = True
                    else:
                        ojos_detectados = False
                except Exception:
                    ojos_detectados = False

                # boca
                try:
                    mouth_top = pts[13]
                    mouth_bottom = pts[14]
                    mouth_h = StreamState._calcular_dist(mouth_top, mouth_bottom)
                    nose_pt = pts[NOSE_IDX]
                    chin_pt = pts[CHIN_IDX]
                    face_h = StreamState._calcular_dist(nose_pt, chin_pt) if StreamState._calcular_dist(nose_pt, chin_pt) != 0 else 1
                    mouth_ratio = mouth_h / face_h
                    boca_detectada = mouth_ratio > MOUTH_OPEN_THRESHOLD
                except Exception:
                    boca_detectada = False

                # cabeza
                try:
                    ys = [p[1] for p in pts]
                    top_y = min(ys)
                    bottom_y = max(ys)
                    nose_y = pts[NOSE_IDX][1]
                    if bottom_y - top_y > 0:
                        nose_rel = (nose_y - top_y) / (bottom_y - top_y)
                        if nose_rel > (0.5 + HEAD_DOWN_THRESHOLD):
                            head_down = True
                except Exception:
                    head_down = False

                # dibujar indicadores ligeros
                cv2.putText(frame, f"EAR: {ear:.2f}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,0), 2)
                if 'mouth_ratio' in locals():
                    cv2.putText(frame, f"MouthRatio: {mouth_ratio:.2f}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,0), 2)
                if head_down:
                    cv2.putText(frame, "HEAD DOWN", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)

            # lógica de puntaje
            tiene_cara = bool(results and results.multi_face_landmarks)
            if not ojos_detectados and tiene_cara:
                frames_no_eyes += 1
            else:
                frames_no_eyes = 0

            if ear < EAR_THRESHOLD and tiene_cara:
                frames_eyes_closed += 1
            else:
                frames_eyes_closed = 0

            if frames_no_eyes > EAR_CONSEC_FRAMES:
                self.score -= SCORE_DECREMENT_NO_EYES
            else:
                if ojos_detectados:
                    self.score += SCORE_INCREMENT_EYES_OPEN

            if frames_eyes_closed >= EAR_CONSEC_FRAMES:
                self.score -= SCORE_DECREMENT_EYES_CLOSED

            if boca_detectada:
                self.score -= SCORE_DECREMENT_YAWN

            if head_down:
                self.score -= SCORE_DECREMENT_HEAD_DOWN

            self.score = max(SCORE_MIN, min(SCORE_MAX, self.score))

            # If score falls below alert threshold and cooldown passed, notify callbacks
            if self.score < ALERT_THRESHOLD and time.time() - self.last_alert > ALERT_COOLDOWN:
                self.last_alert = time.time()
                # call registered callbacks asynchronously
                for cb in list(_callbacks):
                    try:
                        threading.Thread(target=cb, args=(self.source, int(self.score)), daemon=True).start()
                    except Exception:
                        pass

            # update frame and score protected
            with self.lock:
                # encode frame to JPEG for MJPEG
                try:
                    _, jpeg = cv2.imencode('.jpg', frame)
                    self.frame = jpeg.tobytes()
                except Exception:
                    self.frame = None

            counter += 1
            time.sleep(0.03)

        cap.release()
        if face_mesh and hasattr(face_mesh, 'close'):
            face_mesh.close()
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)


# manager global por fuente
_streams = {}
# callbacks que serán invocados cuando haya alerta: cb(source_key, score)
_callbacks = []

def register_callback(cb):
    if cb not in _callbacks:
        _callbacks.append(cb)

def unregister_callback(cb):
    if cb in _callbacks:
        _callbacks.remove(cb)


def get_stream_state(source_key):
    # source_key is string identifying the source (e.g. conductor id or camera url)
    if source_key in _streams:
        return _streams[source_key]
    s = StreamState(source_key)
    _streams[source_key] = s
    s.start()
    return s


def mjpeg_generator_for(conductor):
    """
    Genera un stream MJPEG para el administrador.
    Prioriza frames empujados desde el navegador del conductor.
    Si no hay push: usa la fuente de cámara configurada (camera_source) si existe.
    Si no hay nada: emite un placeholder.
    """
    conductor_id = str(conductor.id)
    print(f"[INFO] Iniciando MJPEG stream para conductor {conductor_id}")
    
    frame_count = 0
    # Modo híbrido continuo: revisar fuentes en cada iteración
    while True:
        frame_to_send = None
        sleep_time = 0.1
        
        # 1) Prioridad: frames push desde navegador
        state = _conductor_states.get(conductor_id)
        if state and state.get('last_jpeg'):
            frame_to_send = state['last_jpeg']
            sleep_time = 0.05  # 20 fps para push
            frame_count += 1
            if frame_count == 1:
                print(f"[INFO] Stream activo para conductor {conductor_id} (modo push)")
        
        # 2) Fallback: camera_source física si está configurada
        elif getattr(conductor, 'camera_source', None) and getattr(conductor, 'camera_source', None) in _streams:
            source = conductor.camera_source
            stream_state = _streams[source]
            with stream_state.lock:
                if stream_state.frame:
                    frame_to_send = stream_state.frame
                    sleep_time = 0.05
        
        # 3) Generar frame apropiado
        if frame_to_send:
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_to_send + b'\r\n')
        else:
            # Placeholder cuando no hay señal disponible
            img = 255 * (np.ones((480, 640, 3), dtype='uint8'))
            cv2.putText(img, 'SIN SEÑAL', (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (100, 100, 100), 3)
            cv2.putText(img, 'Esperando transmision...', (150, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
            _, jpeg = cv2.imencode('.jpg', img)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            sleep_time = 0.3
        
        time.sleep(sleep_time)


def get_score_for(conductor):
    """
    Obtiene el score actual para el conductor.
    Si hay estado de push (navegador), devuelve ese score.
    En su defecto, si hay camera_source, devuelve el score del flujo de dispositivo.
    Si no hay nada, devuelve SCORE_START.
    """
    conductor_id = str(conductor.id)
    # Preferir el score del estado de push
    if conductor_id in _conductor_states:
        return max(SCORE_MIN, min(SCORE_MAX, int(_conductor_states[conductor_id].get('score', SCORE_START))))

    # Luego intentar usar camera_source si existe
    source = getattr(conductor, 'camera_source', None)
    if source:
        state = get_stream_state(source)
        return max(SCORE_MIN, min(SCORE_MAX, int(state.score)))

    # Fallback
    return SCORE_START


# Diccionario para mantener el estado de cada conductor que transmite desde el navegador
_conductor_states = {}

def process_frame_for_conductor(conductor, frame):
    """
    Procesa un frame individual enviado desde el navegador del conductor.
    Retorna el score de somnolencia.
    """
    conductor_id = str(conductor.id)
    
    # Inicializar estado si no existe
    if conductor_id not in _conductor_states:
        _conductor_states[conductor_id] = {
            'score': SCORE_START,
            'frames_no_eyes': 0,
            'frames_eyes_closed': 0,
            'last_alert': 0,
            'last_jpeg': None,
            'last_jpeg_encode': 0.0,
            'last_update': time.time(),
            'lock': threading.Lock(),
            'face_mesh': _create_face_mesh(),
            'chin_positions': deque(maxlen=8),  # Para detectar cabeceo
            'sustained_drowsy_start': None,  # Marca cuando empieza somnolencia sostenida
            'no_face_streak': 0,
            'last_face_detected': True,
            'location': None  # {'lat': float, 'lon': float, 'timestamp': float}
        }
    
    state = _conductor_states[conductor_id]

    # Compatibilidad: si el estado fue creado por update_location_for,
    # puede venir incompleto. Completamos claves críticas aquí.
    if 'lock' not in state:
        state['lock'] = threading.Lock()
    if 'face_mesh' not in state:
        state['face_mesh'] = _create_face_mesh()
    state.setdefault('frames_no_eyes', 0)
    state.setdefault('frames_eyes_closed', 0)
    state.setdefault('last_alert', 0)
    state.setdefault('last_jpeg', None)
    state.setdefault('last_jpeg_encode', 0.0)
    state.setdefault('last_update', time.time())
    if not isinstance(state.get('chin_positions'), deque):
        state['chin_positions'] = deque(state.get('chin_positions', []), maxlen=8)
    state.setdefault('sustained_drowsy_start', None)
    state.setdefault('no_face_streak', 0)
    state.setdefault('last_face_detected', True)
    state.setdefault('score', SCORE_START)
    
    # Usar lock para evitar procesamiento concurrente
    with state['lock']:
        face_mesh = state['face_mesh']
        analysis_frame = _resize_for_analysis(frame)
        h, w = analysis_frame.shape[:2]
        rgb = cv2.cvtColor(analysis_frame, cv2.COLOR_BGR2RGB)
        
        # Manejar errores de timestamp de MediaPipe
        try:
            results = face_mesh.process(rgb) if face_mesh else None
        except ValueError as e:
            if "timestamp" in str(e).lower():
                print(f"[WARN] MediaPipe timestamp error para {conductor_id}, reiniciando FaceMesh")
                if state.get('face_mesh') and hasattr(state['face_mesh'], 'close'):
                    state['face_mesh'].close()
                state['face_mesh'] = _create_face_mesh()
                face_mesh = state['face_mesh']
                results = face_mesh.process(rgb) if face_mesh else None
            else:
                raise
        
        ojos_detectados = False
        boca_detectada = False
        head_down = False
        head_nod_detected = False
        ear = 0.0
        ear_valid = False
        
        if results and results.multi_face_landmarks:
            face_landmarks = results.multi_face_landmarks[0]
            lm = face_landmarks.landmark
            pts = [(int(p.x * w), int(p.y * h)) for p in lm]
            
            # Calcular EAR (Eye Aspect Ratio)
            try:
                left_eye_pts = [pts[idx] for idx in LEFT_EYE_IDX]
                right_eye_pts = [pts[idx] for idx in RIGHT_EYE_IDX]
                ear_left = StreamState._calcular_EAR(left_eye_pts)
                ear_right = StreamState._calcular_EAR(right_eye_pts)
                ear = (ear_left + ear_right) / 2.0
                ojos_detectados = ear > 0.01
                ear_valid = True
            except Exception:
                ojos_detectados = False
            
            # Detectar bostezo
            try:
                mouth_top = pts[13]
                mouth_bottom = pts[14]
                mouth_h = StreamState._calcular_dist(mouth_top, mouth_bottom)
                nose_pt = pts[NOSE_IDX]
                chin_pt = pts[CHIN_IDX]
                face_h = StreamState._calcular_dist(nose_pt, chin_pt)
                if face_h == 0:
                    face_h = 1
                mouth_ratio = mouth_h / face_h
                boca_detectada = mouth_ratio > MOUTH_OPEN_THRESHOLD
            except Exception:
                boca_detectada = False
            
            # Detectar cabeza inclinada
            try:
                ys = [p[1] for p in pts]
                top_y = min(ys)
                bottom_y = max(ys)
                nose_y = pts[NOSE_IDX][1]
                chin_y = pts[CHIN_IDX][1]
                
                if bottom_y - top_y > 0:
                    nose_rel = (nose_y - top_y) / (bottom_y - top_y)
                    if nose_rel > (0.5 + HEAD_DOWN_THRESHOLD):
                        head_down = True
                
                # Detectar cabeceo (movimientos bruscos del mentón)
                state['chin_positions'].append(chin_y)
                if len(state['chin_positions']) >= 5:
                    chin_variance = max(state['chin_positions']) - min(state['chin_positions'])
                    if bottom_y - top_y > 0:
                        chin_variance_norm = chin_variance / (bottom_y - top_y)
                        if chin_variance_norm > HEAD_NOD_THRESHOLD:
                            head_nod_detected = True
            except Exception:
                head_down = False
        
        # Lógica de puntaje mejorada
        tiene_cara = bool(results and results.multi_face_landmarks)
        if not tiene_cara:
            state['no_face_streak'] += 1
            if state['no_face_streak'] == 1 or state['no_face_streak'] % HAAR_RECHECK_INTERVAL == 0:
                gray = cv2.cvtColor(analysis_frame, cv2.COLOR_BGR2GRAY)
                tiene_cara, ojos_haar = _detect_face_eyes_haar(analysis_frame, gray=gray)
            else:
                ojos_haar = False
            if tiene_cara:
                ojos_detectados = ojos_haar
        else:
            state['no_face_streak'] = 0
        state['last_face_detected'] = tiene_cara
        
        if not ojos_detectados and tiene_cara:
            state['frames_no_eyes'] += 1
        else:
            state['frames_no_eyes'] = 0
        
        if ear_valid and ear < EAR_THRESHOLD and tiene_cara:
            state['frames_eyes_closed'] += 1
        elif (not ear_valid) and tiene_cara and (not ojos_detectados):
            state['frames_eyes_closed'] += 1
        else:
            state['frames_eyes_closed'] = 0
        
        # Detectar somnolencia sostenida
        is_drowsy = (state['frames_eyes_closed'] >= EAR_CONSEC_FRAMES or 
                     state['frames_no_eyes'] > EAR_CONSEC_FRAMES)
        
        if is_drowsy:
            if state['sustained_drowsy_start'] is None:
                state['sustained_drowsy_start'] = time.time()
            drowsy_duration = time.time() - state['sustained_drowsy_start']
            # Penalización creciente con el tiempo: alcanza 3x en ~4 segundos
            time_multiplier = 1.0 + min(drowsy_duration / 2.0, 3.0)  # Max 4x después de 6s
        else:
            state['sustained_drowsy_start'] = None
            time_multiplier = 1.0
        
        # Aplicar decrementos/incrementos
        if not tiene_cara:
            # Sin cara detectada: penalizar levemente (evita que el score se quede fijo en 100)
            state['score'] -= SCORE_DECREMENT_NO_FACE
        elif state['frames_no_eyes'] > EAR_CONSEC_FRAMES:
            state['score'] -= SCORE_DECREMENT_NO_EYES * time_multiplier
        else:
            if ojos_detectados:
                state['score'] += SCORE_INCREMENT_EYES_OPEN
        
        if state['frames_eyes_closed'] >= EAR_CONSEC_FRAMES:
            state['score'] -= SCORE_DECREMENT_EYES_CLOSED * time_multiplier
        
        if boca_detectada:
            state['score'] -= SCORE_DECREMENT_YAWN
        
        if head_down:
            state['score'] -= SCORE_DECREMENT_HEAD_DOWN * time_multiplier
        
        if head_nod_detected:
            state['score'] -= SCORE_DECREMENT_HEAD_NOD * time_multiplier
            # Penalización adicional cuando hay cabeceo y ojos cerrados simultáneamente
            if state['frames_eyes_closed'] >= EAR_CONSEC_FRAMES:
                state['score'] -= SCORE_DECREMENT_NOD_EYES * time_multiplier
        
        state['score'] = max(SCORE_MIN, min(SCORE_MAX, state['score']))
        
        # Alertas
        if state['score'] < ALERT_THRESHOLD and time.time() - state['last_alert'] > ALERT_COOLDOWN:
            state['last_alert'] = time.time()
            for cb in list(_callbacks):
                try:
                    threading.Thread(target=cb, args=(conductor_id, int(state['score'])), daemon=True).start()
                except Exception:
                    pass
        
        # Guardar último frame como JPEG para el stream MJPEG del admin
        try:
            now = time.time()
            if state['last_jpeg'] is None or (now - state['last_jpeg_encode']) >= MJPEG_ENCODE_INTERVAL:
                _, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                state['last_jpeg'] = jpeg.tobytes()
                state['last_jpeg_encode'] = now
            state['last_update'] = now
            # Log solo en el primer frame para confirmar
            if 'frame_count' not in state:
                state['frame_count'] = 0
                print(f"[INFO] Primer frame recibido para conductor {conductor_id}")
            state['frame_count'] += 1
        except Exception as e:
            print(f"[ERROR] No se pudo guardar frame para conductor {conductor_id}: {e}")

        return max(SCORE_MIN, min(SCORE_MAX, int(state['score']))), tiene_cara


def stop_stream_for(conductor):
    """
    Limpia el estado de un conductor cuando deja de transmitir.
    """
    conductor_id = str(conductor.id)
    if conductor_id in _conductor_states:
        # Cerrar face_mesh si existe
        if 'face_mesh' in _conductor_states[conductor_id]:
            try:
                _conductor_states[conductor_id]['face_mesh'].close()
            except Exception:
                pass
        # Limpiar last_jpeg para que el generador muestre "SIN SEÑAL"
        _conductor_states[conductor_id]['last_jpeg'] = None
        print(f"[INFO] Stream detenido para conductor {conductor_id}, limpiando frames")
        del _conductor_states[conductor_id]


def update_location_for(conductor, lat, lon):
    """Actualiza la ubicación actual (lat, lon) para el conductor en memoria.
    Se guarda solo en memoria para mostrar en el dashboard del administrador.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return
    conductor_id = str(conductor.id)
    if conductor_id not in _conductor_states:
        # Inicializar estado completo para evitar KeyError en procesamiento posterior.
        _conductor_states[conductor_id] = {
            'score': SCORE_START,
            'frames_no_eyes': 0,
            'frames_eyes_closed': 0,
            'last_alert': 0,
            'last_jpeg': None,
            'last_update': time.time(),
            'lock': threading.Lock(),
            'face_mesh': _create_face_mesh(),
            'chin_positions': [],
            'sustained_drowsy_start': None,
            'location': None
        }
    state = _conductor_states[conductor_id]
    state['location'] = {
        'lat': lat_f,
        'lon': lon_f,
        'timestamp': time.time()
    }


def get_locations_snapshot():
    """Retorna un dict {conductor_id: {lat, lon, timestamp}} de las ubicaciones actuales."""
    snapshot = {}
    for cid, state in _conductor_states.items():
        loc = state.get('location')
        if loc:
            snapshot[cid] = {
                'lat': loc['lat'],
                'lon': loc['lon'],
                'timestamp': loc['timestamp']
            }
    return snapshot
