---

# 🚨 **Backend – Alerta UTEC (Documentación Oficial)**

Este backend implementa una plataforma **serverless en AWS** para reportar, gestionar y monitorear incidentes dentro del campus UTEC.
El sistema está diseñado para funcionar **100% en la nube**, con notificaciones **en tiempo real** mediante WebSocket y envíos de correo a los administradores mediante **SNS**.

---

# 🏗️ **Arquitectura General**

```
Frontend (React/Vite)
      │   REST API (POST /incidentes)
      ▼
AWS API Gateway (HTTP API)
      ▼
Lambda: crear_incidente
      ├── Guarda en DynamoDB (t_incidentes)
      ├── Envía correo vía SNS (topic de alertas)
      └── Notifica en tiempo real vía WebSocket
           
AWS API Gateway (WebSocket API)
      ├── $connect      → guarda la conexión
      ├── $disconnect   → elimina la conexión
      └── $default      → mensajes genéricos
           
DynamoDB
      ├── Tabla de incidentes
      └── Tabla de conexiones WebSocket
```

---

# 🚨 **Flujo Completo al Reportar un Incidente**

Cuando un usuario reporta un incidente desde el frontend:

### 1️⃣ Envia un `POST /incidentes`

Con datos como:

```json
{
  "title": "Fuga de agua",
  "location": "Pabellón A",
  "urgency": "alta",
  "description": "Agua saliendo del baño"
}
```

### 2️⃣ La Lambda `crear_incidente` realiza:

✔ Genera `incidentId` y timestamp
✔ Guarda el incidente en **DynamoDB**
✔ Publica el incidente por correo usando **SNS** (a administradores suscritos)
✔ Envía una notificación en tiempo real a **todos los dashboards WebSocket conectados**

El mensaje enviado por WebSocket tiene esta estructura:

```json
{
  "action": "notify",
  "incident": { ... }
}
```

### 3️⃣ Los dashboards conectados al WebSocket reciben la alerta al instante ⚡

---

# 🧩 **Componentes del Backend**

---

## **1. API REST (HTTP API)**

La API REST maneja el CRUD básico de incidentes.

### 📌 **POST /incidentes**

Crea un incidente y dispara:

* guardado en DynamoDB
* envío a SNS
* notificación WebSocket

### 📌 **GET /incidentes**

Devuelve todos los incidentes registrados.

### 📌 **PATCH /incidentes/{id}**

Actualiza uno o varios atributos del incidente.

---

## **2. WebSocket API – Notificaciones en Tiempo Real**

La WebSocket API maneja conexiones persistentes para dashboards administrativos.

### 🔌 `$connect`

Guarda el `connectionId` del cliente en DynamoDB.

### 🔌 `$disconnect`

Elimina la conexión de la tabla.

### 🔌 `$default`

Recibe mensajes genéricos desde clientes WebSocket (opcional).

### 📤 **Broadcasting (Backend → WebSocket)**

Cualquier cambio en incidentes se envía con:

```
apigatewaymanagementapi.post_to_connection()
```

Esto permite que cualquier pantalla o dashboard conectado reciba:

```json
{
  "action": "notify",
  "incident": {...}
}
```

---

## **3. DynamoDB**

### 📁 Tabla de Incidentes

Guarda:

* `incidentId`
* `title`
* `description`
* `location`
* `urgency`
* `status`
* `reportedBy`
* `createdAt`

### 📁 Tabla de Conexiones WebSocket

Guarda:

* `connectionId`

Se usa para enviar mensajes a todos los clientes conectados.

---

## **4. SNS – Envío de Correos Automáticos**

Cada vez que se crea un incidente:

```
sns.publish(TopicArn=SNS_TOPIC_ARN, Message=mensaje)
```

Los administradores suscritos al topic reciben un correo con:

* título
* ubicación
* urgencia
* descripción
* fecha
* ID del incidente

---

# 🧨 **CORS Habilitado**

El backend habilita CORS para que el frontend pueda consumir la API desde Vite:

```yaml
httpApi:
  cors:
    allowedOrigins:
      - http://localhost:5173
      - "*"
    allowedMethods:
      - GET
      - POST
      - PATCH
      - OPTIONS
    allowedHeaders:
      - Content-Type
```

---

# 🔥 **Características Clave del Backend**

* Totalmente serverless → no requiere servidores
* Notificaciones en tiempo real
* Envío automático de correos por SNS
* Integración REST + WebSocket
* Tablas DynamoDB sin necesidad de índices secundarios
* Compatible con cualquier frontend (React, Vue, Angular, móvil)

---

# 🧪 **Cómo probar**

### 🟦 Conectarse al WebSocket:

```
wss://zisd0y9a8j.execute-api.us-east-1.amazonaws.com/dev
```

### 🟧 Enviar POST (crear incidente):

```
POST https://<api-id>.execute-api.us-east-1.amazonaws.com/incidentes
```

Body:

```json
{
  "title": "Prueba hackathon",
  "location": "Laboratorio 3",
  "urgency": "alta",
  "description": "Simulación"
}
```

### Resultado:

* Mensaje aparece en dashboard WebSocket
* Correo recibido por SNS
* Incidente guardado en DynamoDB

---

# 🎉 **Conclusión**

El backend de Alerta UTEC combina REST + WebSocket + SNS en una arquitectura serverless que permite:

* registrar incidentes desde cualquier dispositivo
* notificar a administradores automáticamente
* distribuir alertas en tiempo real a múltiples dashboards
* escalar sin servidores ni costos fijos
