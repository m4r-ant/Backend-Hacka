import json
import os
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
INCIDENTS_TABLE_NAME = os.environ["INCIDENTS_TABLE"]
incidents_table = dynamodb.Table(INCIDENTS_TABLE_NAME)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # para frontend
        },
        "body": json.dumps(body),
    }


def crear_incidente(event, context):
    """
    POST /incidentes
    Body JSON:
    {
      "type": "infraestructura",
      "location": "Piso 3, aula 304",
      "description": "Fuga de agua",
      "urgency": "alta"
    }
    """
    try:
        body = json.loads(event.get("body") or "{}")
        now = datetime.utcnow().isoformat()

        incident_id = str(uuid.uuid4())

        item = {
            "incidentId": incident_id,
            "type": body.get("type", "otro"),
            "location": body.get("location", "desconocida"),
            "description": body.get("description", ""),
            "urgency": body.get("urgency", "media"),
            "status": "pendiente",
            "createdAt": now,
            "updatedAt": now,
            # Aquí podrías agregar createdBy, rol, etc (con Cognito)
        }

        incidents_table.put_item(Item=item)

        return _response(201, item)
    except Exception as e:
        print("Error en crear_incidente:", e)
        return _response(500, {"error": "Error creando incidente"})


def listar_incidentes(event, context):
    """
    GET /incidentes
    Opcionalmente podrías filtrar por status via queryStringParameters.
    """
    try:
        res = incidents_table.scan()
        items = res.get("Items", [])
        return _response(200, items)
    except Exception as e:
        print("Error en listar_incidentes:", e)
        return _response(500, {"error": "Error listando incidentes"})


def actualizar_incidente(event, context):
    """
    PATCH /incidentes/{id}
    Body JSON (ejemplo):
    {
      "status": "en_atencion",
      "assignedTo": "Mantenimiento"
    }
    """
    try:
        incident_id = event["pathParameters"]["id"]
        body = json.loads(event.get("body") or "{}")

        # Leemos el incidente actual
        current = incidents_table.get_item(Key={"incidentId": incident_id}).get("Item")
        if not current:
            return _response(404, {"error": "Incidente no encontrado"})

        now = datetime.utcnow().isoformat()

        updated = {
            **current,
            "status": body.get("status", current.get("status", "pendiente")),
            "assignedTo": body.get("assignedTo", current.get("assignedTo", None)),
            "updatedAt": now,
        }

        incidents_table.put_item(Item=updated)

        # Aquí podrías llamar a WebSocket (broadcast) usando API Gateway Management API
        # o dejar que el frontend dispare el broadcast.

        return _response(200, updated)
    except Exception as e:
        print("Error en actualizar_incidente:", e)
        return _response(500, {"error": "Error actualizando incidente"})
