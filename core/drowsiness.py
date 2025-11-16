import cv2
import numpy as np
import threading
import time
import math
import mediapipe as mp

# Simple manager que mantiene un hilo por fuente de cámara (por conductor)
# y ofrece un frame MJPEG y un puntaje actual en memoria.

mp_face_mesh = mp.solutions.face_mesh

LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]
NOSE_IDX = 1
CHIN_IDX = 152

# Parámetros mejorados para detección de somnolencia
FPS_SAVE = 5
EAR_THRESHOLD = 0.21  # Más sensible: detecta ojos semi-cerrados
EAR_CONSEC_FRAMES = 3  # Respuesta más rápida
MOUTH_OPEN_THRESHOLD = 0.30  # Ajustado para bostezos más sutiles
HEAD_DOWN_THRESHOLD = 0.15  # Más tolerante para cabeza inclinada
HEAD_NOD_THRESHOLD = 0.08  # Detectar cabeceo/movimientos bruscos
SCORE_START = 100
SCORE_MIN = 0
SCORE_MAX = 100
# Ponderaciones ajustadas
SCORE_DECREMENT_EYES_CLOSED = 1.8  # Penaliza más ojos cerrados
SCORE_DECREMENT_NO_EYES = 1.2
SCORE_INCREMENT_EYES_OPEN = 0.6  # Recuperación más rápida
SCORE_DECREMENT_YAWN = 1.5  # Bostezo es señal fuerte
SCORE_DECREMENT_HEAD_DOWN = 1.2
SCORE_DECREMENT_HEAD_NOD = 0.8
SCORE_DECREMENT_NOD_EYES = 3.5  # Penalización combinada fuerte: cabeceo + ojos cerrados
ALERT_THRESHOLD = 30
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

        face_mesh = mp_face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=True,
                                         min_detection_confidence=0.5, min_tracking_confidence=0.5)

        frames_no_eyes = 0
        frames_eyes_closed = 0
        counter = 0

        while self.running:
            ret, frame = cap.read()
            if not ret:
                break
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

            ojos_detectados = False
            boca_detectada = False
            head_down = False
            ear = 0.0

            if results.multi_face_landmarks:
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
            tiene_cara = bool(results.multi_face_landmarks)
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
            'last_update': time.time(),
            'lock': threading.Lock(),
            'face_mesh': mp_face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            ),
            'chin_positions': [],  # Para detectar cabeceo
            'sustained_drowsy_start': None  # Marca cuando empieza somnolencia sostenida
        }
    
    state = _conductor_states[conductor_id]
    
    # Usar lock para evitar procesamiento concurrente
    with state['lock']:
        face_mesh = state['face_mesh']
        
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Manejar errores de timestamp de MediaPipe
        try:
            results = face_mesh.process(rgb)
        except ValueError as e:
            if "timestamp" in str(e).lower():
                print(f"[WARN] MediaPipe timestamp error para {conductor_id}, reiniciando FaceMesh")
                state['face_mesh'].close()
                state['face_mesh'] = mp_face_mesh.FaceMesh(
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5
                )
                face_mesh = state['face_mesh']
                results = face_mesh.process(rgb)
            else:
                raise
        
        ojos_detectados = False
        boca_detectada = False
        head_down = False
        head_nod_detected = False
        ear = 0.0
        
        if results.multi_face_landmarks:
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
                if len(state['chin_positions']) > 10:  # Mantener ventana de 10 frames
                    state['chin_positions'].pop(0)
                    if len(state['chin_positions']) >= 5:
                        chin_variance = max(state['chin_positions']) - min(state['chin_positions'])
                        # Normalizar por altura de cara
                        if bottom_y - top_y > 0:
                            chin_variance_norm = chin_variance / (bottom_y - top_y)
                            if chin_variance_norm > HEAD_NOD_THRESHOLD:
                                head_nod_detected = True
            except Exception:
                head_down = False
        
        # Lógica de puntaje mejorada
        tiene_cara = bool(results.multi_face_landmarks)
        
        if not ojos_detectados and tiene_cara:
            state['frames_no_eyes'] += 1
        else:
            state['frames_no_eyes'] = 0
        
        if ear < EAR_THRESHOLD and tiene_cara:
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
            # Penalización creciente con el tiempo (multiplicador de duración)
            time_multiplier = 1.0 + min(drowsy_duration / 5.0, 2.0)  # Max 3x después de 10s
        else:
            state['sustained_drowsy_start'] = None
            time_multiplier = 1.0
        
        # Aplicar decrementos/incrementos
        if state['frames_no_eyes'] > EAR_CONSEC_FRAMES:
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
            state['score'] -= SCORE_DECREMENT_HEAD_NOD
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
            _, jpeg = cv2.imencode('.jpg', frame)
            state['last_jpeg'] = jpeg.tobytes()
            state['last_update'] = time.time()
            # Log solo en el primer frame para confirmar
            if 'frame_count' not in state:
                state['frame_count'] = 0
                print(f"[INFO] Primer frame recibido para conductor {conductor_id}")
            state['frame_count'] += 1
        except Exception as e:
            print(f"[ERROR] No se pudo guardar frame para conductor {conductor_id}: {e}")

        return max(SCORE_MIN, min(SCORE_MAX, int(state['score'])))


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
