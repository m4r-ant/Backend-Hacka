# handlers/incident_handler.py
import json
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
ses = boto3.client("ses")

INCIDENTS_TABLE = os.environ.get("INCIDENTS_TABLE")
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT")
QA_EMAILS = os.environ.get("QA_EMAILS", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL")


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": True,
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def _send_email_to_qa(incident):
    """
    Envía correo a los QA usando Amazon SES.
    QA_EMAILS = "qa1@...,qa2@..."
    FROM_EMAIL debe estar verificado en SES.
    """
    if not QA_EMAILS or not FROM_EMAIL:
        print("QA_EMAILS o FROM_EMAIL no configurados, no se enviará correo.")
        return

    recipients = [e.strip() for e in QA_EMAILS.split(",") if e.strip()]
    if not recipients:
        print("No hay correos QA válidos.")
        return

    subject = f"Nuevo incidente reportado: {incident.get('title', 'Sin título')}"
    body_text = (
        "Se ha registrado un nuevo incidente:\n\n"
        f"ID: {incident.get('incidentId')}\n"
        f"Título: {incident.get('title')}\n"
        f"Descripción: {incident.get('description')}\n"
        f"Ubicación: {incident.get('location')}\n"
        f"Urgencia: {incident.get('urgency')}\n"
        f"Estado: {incident.get('status')}\n"
        f"Reportado por: {incident.get('reportedBy')}\n"
        f"Fecha: {incident.get('createdAt')}\n"
    )

    try:
        print(f"Enviando correo a QA: {recipients}")
        ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": recipients},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body_text}},
            },
        )
    except ClientError as e:
        print("Error enviando correo SES:", e)


def _get_apigw_client():
    """
    Cliente para API Gateway Management API, usando el WS_ENDPOINT
    que tienes configurado en las env vars.
    """
    if not WS_ENDPOINT:
        raise RuntimeError("WS_ENDPOINT no está configurado")

    return boto3.client("apigatewaymanagementapi", endpoint_url=WS_ENDPOINT)


def _notify_all_connections(payload):
    """
    Envía un mensaje con action: "notify" a TODAS las conexiones
    guardadas en la tabla CONNECTIONS_TABLE.
    """
    if not CONNECTIONS_TABLE:
        print("CONNECTIONS_TABLE no configurado, no se enviarán notificaciones.")
        return

    table = dynamodb.Table(CONNECTIONS_TABLE)
    apigw = _get_apigw_client()

    # message que verá el WebSocket en el front
    message = {
        "action": "notify",  # 👈 lo que tu front va a leer
        **payload,
    }

    data_bytes = json.dumps(message).encode("utf-8")

    scan_kwargs = {"TableName": CONNECTIONS_TABLE}
    response = table.scan()
    connections = response.get("Items", [])

    print(f"Enviando notificación a {len(connections)} conexiones WebSocket.")

    for conn in connections:
        connection_id = conn.get("connectionId")
        if not connection_id:
            continue

        try:
            apigw.post_to_connection(ConnectionId=connection_id, Data=data_bytes)
        except ClientError as e:
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            print(f"Error enviando a {connection_id}: {e}")
            if status == 410:
                # Conexión muerta, la borramos
                print(f"Conexión {connection_id} muerta, eliminando.")
                table.delete_item(Key={"connectionId": connection_id})


# ---------- HANDLERS PUBLICOS ----------

def crear_incidente(event, context):
    """
    POST /incidentes
    Crea incidente, envía correo QA y notifica via WebSocket (action: 'notify')
    """
    print("Evento crear_incidente:", event)

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"message": "Body inválido, debe ser JSON"})

    incident_id = str(uuid.uuid4())
    now_iso = datetime.utcnow().isoformat()

    incident = {
        "incidentId": incident_id,
        "title": body.get("title", "Incidente sin título"),
        "description": body.get("description", ""),
        "location": body.get("location", ""),
        "urgency": body.get("urgency", "media"),
        "status": body.get("status", "pendiente"),
        "reportedBy": body.get("reportedBy", "anónimo"),
        "createdAt": now_iso,
    }

    table = dynamodb.Table(INCIDENTS_TABLE)

    try:
        table.put_item(Item=incident)
        # 1. Enviar correo a QA
        _send_email_to_qa(incident)
        # 2. Notificar a todos los clientes WebSocket
        _notify_all_connections(
            {
                "incidentId": incident_id,
                "title": incident["title"],
                "urgency": incident["urgency"],
                "location": incident["location"],
                "status": incident["status"],
                "createdAt": incident["createdAt"],
            }
        )

        return _response(
            201,
            {
                "ok": True,
                "message": "Incidente creado, correo enviado y notificación enviada",
                "incident": incident,
            },
        )
    except ClientError as e:
        print("Error al crear incidente:", e)
        return _response(
            500,
            {"ok": False, "message": "Error al crear incidente", "error": str(e)},
        )


def listar_incidentes(event, context):
    """
    GET /incidentes
    """
    print("Evento listar_incidentes:", event)

    table = dynamodb.Table(INCIDENTS_TABLE)
    try:
        resp = table.scan()
        items = resp.get("Items", [])
        return _response(200, {"ok": True, "items": items})
    except ClientError as e:
        print("Error al listar incidentes:", e)
        return _response(500, {"ok": False, "message": "Error al listar", "error": str(e)})


def actualizar_incidente(event, context):
    """
    PATCH /incidentes/{id}
    """
    print("Evento actualizar_incidente:", event)

    path_params = event.get("pathParameters") or {}
    incident_id = path_params.get("id")

    if not incident_id:
        return _response(400, {"message": "Falta id en la ruta"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"message": "Body inválido, debe ser JSON"})

    # Construimos UpdateExpression dinámico
    update_expr_parts = []
    expr_attr_values = {}
    expr_attr_names = {}

    for key in ["title", "description", "location", "urgency", "status", "reportedBy"]:
        if key in body:
            update_expr_parts.append(f"#k_{key} = :v_{key}")
            expr_attr_values[f":v_{key}"] = body[key]
            expr_attr_names[f"#k_{key}"] = key

    if not update_expr_parts:
        return _response(400, {"message": "No hay campos para actualizar"})

    update_expr = "SET " + ", ".join(update_expr_parts)

    table = dynamodb.Table(INCIDENTS_TABLE)

    try:
        resp = table.update_item(
            Key={"incidentId": incident_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )

        updated = resp.get("Attributes", {})
        return _response(200, {"ok": True, "incident": updated})
    except ClientError as e:
        print("Error al actualizar incidente:", e)
        return _response(500, {"ok": False, "message": "Error al actualizar", "error": str(e)})
