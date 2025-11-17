# handlers/incident_handler.py

import json
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

# -------- Variables de entorno --------

INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE")
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)


# -----------------------------------------------------
# RESPUESTA ESTÁNDAR (CON CORS)
# -----------------------------------------------------

def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",   # o "http://localhost:5173"
            "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Credentials": True,
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


# -----------------------------------------------------
# WEB SOCKET MANAGEMENT API
# -----------------------------------------------------

def _get_apigw_client():
    if not WS_ENDPOINT:
        raise RuntimeError("WS_ENDPOINT no configurado")

    return boto3.client("apigatewaymanagementapi", endpoint_url=WS_ENDPOINT)


def _notify_all_connections(incident, action="notify"):
    """
    Envía mensaje WebSocket: { action: "...", incident: {...} }
    a todas las conexiones activas en DynamoDB.
    """
    table = dynamodb.Table(CONNECTIONS_TABLE)
    apigw = _get_apigw_client()

    message = {
        "action": action,
        "incident": incident,
    }

    data_bytes = json.dumps(message).encode("utf-8")

    resp = table.scan()
    connections = resp.get("Items", [])

    print(f"Notificando a {len(connections)} conexiones WebSocket...")

    for conn in connections:
        connection_id = conn.get("connectionId")
        if not connection_id:
            continue

        try:
            apigw.post_to_connection(
                ConnectionId=connection_id,
                Data=data_bytes
            )
        except ClientError as e:
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            print(f"Error enviando a {connection_id}: {e}")

            # 410: conexión muerta → eliminar de DynamoDB
            if status == 410:
                print(f"Conexión {connection_id} muerta. Eliminando.")
                table.delete_item(Key={"connectionId": connection_id})


# -----------------------------------------------------
# SNS (CORREOS)
# -----------------------------------------------------

def _publish_to_sns(incident):
    print("Publicando incidente en SNS...")

    if not SNS_TOPIC_ARN:
        print("SNS_TOPIC_ARN no configurado.")
        return

    subject = f"Nuevo incidente: {incident.get('title')}"

    message = (
        "Se ha registrado un nuevo incidente:\n\n"
        f"ID: {incident.get('incidentId')}\n"
        f"Título: {incident.get('title')}\n"
        f"Descripción: {incident.get('description')}\n"
        f"Ubicación: {incident.get('location')}\n"
        f"Urgencia: {incident.get('urgency')}\n"
        f"Estado: {incident.get('status')}\n"
        f"Reporte: {incident.get('reportedBy')}\n"
        f"Fecha: {incident.get('createdAt')}\n"
    )

    try:
        resp = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
        )
        print("SNS enviado correctamente. MessageId:", resp.get("MessageId"))
    except Exception as e:
        print("Error enviando SNS:", e)


# -----------------------------------------------------
# POST /incidentes   (CREAR INCIDENTE)
# -----------------------------------------------------

def crear_incidente(event, context):
    """
    Crea un incidente. Soporta dos formatos de body:

    1) SIMPLE (frontend):
        {
          "title": "...",
          "location": "...",
          "description": "...",
          "urgency": "alta",
          "status": "pendiente",
          "reportedBy": "Marco"
        }

    2) FORMATO WS:
        {
          "action": "notify",
          "incident": {
            "type": "infraestructura",
            "location": "...",
            "description": "...",
            "urgency": "alta",
            "status": "pendiente",
            "reportedBy": "Marco"
          }
        }
    """

    print("Evento crear_incidente:", event)

    try:
        body = json.loads(event.get("body") or "{}")
    except:
        return _response(400, {"ok": False, "message": "JSON inválido"})

    # Si viene como { incident: {...} }, usamos ese objeto
    if "incident" in body and isinstance(body["incident"], dict):
        payload = body["incident"]
    else:
        payload = body

    # Crear ID y fecha
    incident_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    # Construir incidente final
    incident = {
        "incidentId": incident_id,
        "title": payload.get("title") or payload.get("type") or "Incidente sin título",
        "description": payload.get("description", ""),
        "location": payload.get("location", ""),
        "urgency": payload.get("urgency") or payload.get("priority") or "media",
        "status": payload.get("status", "pendiente"),
        "reportedBy": payload.get("reportedBy", "anónimo"),
        "createdAt": now,
    }

    print("Incidente construido:", incident)

    table = dynamodb.Table(INCIDENTS_TABLE)

    try:
        # 1. Guardar en DynamoDB
        table.put_item(Item=incident)

        # 2. Enviar correo SNS
        _publish_to_sns(incident)

        # 3. Enviar notificación WebSocket
        _notify_all_connections(incident, action="notify")

        return _response(
            201,
            {
                "ok": True,
                "message": "Incidente creado + SNS + WebSocket enviado",
                "incident": incident,
            }
        )

    except Exception as e:
        print("Error creando incidente:", e)
        return _response(500, {"ok": False, "message": "Error interno", "error": str(e)})


# -----------------------------------------------------
# GET /incidentes
# -----------------------------------------------------

def listar_incidentes(event, context):
    print("Evento listar_incidentes:", event)

    table = dynamodb.Table(INCIDENTS_TABLE)

    try:
        resp = table.scan()
        return _response(200, {"ok": True, "items": resp.get("Items", [])})
    except Exception as e:
        print("Error listando incidentes:", e)
        return _response(500, {"ok": False, "message": "Error listando"})


# -----------------------------------------------------
# PATCH /incidentes/{id}
# -----------------------------------------------------

def actualizar_incidente(event, context):
    print("Evento actualizar_incidente:", event)

    params = event.get("pathParameters") or {}
    incident_id = params.get("id")

    if not incident_id:
        return _response(400, {"ok": False, "message": "Falta ID"})

    try:
        body = json.loads(event.get("body") or "{}")
    except:
        return _response(400, {"ok": False, "message": "JSON inválido"})

    update_parts = []
    expr_names = {}
    expr_values = {}

    for key in ["title", "description", "location", "urgency", "status", "reportedBy"]:
        if key in body:
            update_parts.append(f"#k_{key} = :v_{key}")
            expr_names[f"#k_{key}"] = key
            expr_values[f":v_{key}"] = body[key]

    if not update_parts:
        return _response(400, {"ok": False, "message": "Nada que actualizar"})

    table = dynamodb.Table(INCIDENTS_TABLE)

    try:
        resp = table.update_item(
            Key={"incidentId": incident_id},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )

        return _response(200, {"ok": True, "incident": resp.get("Attributes")})

    except Exception as e:
        print("Error actualizando incidente:", e)
        return _response(500, {"ok": False, "message": "Error actualizando"})
