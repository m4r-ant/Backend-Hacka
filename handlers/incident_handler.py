import json
import os
import uuid
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")

INCIDENTS_TABLE_NAME = os.environ["INCIDENTS_TABLE"]
CONNECTIONS_TABLE_NAME = os.environ["CONNECTIONS_TABLE"]
WS_ENDPOINT = os.environ.get("WS_ENDPOINT")

incidents_table = dynamodb.Table(INCIDENTS_TABLE_NAME)
connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # CORS simple
        },
        "body": json.dumps(body),
    }


def _broadcast_ws(message_type: str, payload: dict):
    """
    Envía un mensaje a TODOS los clientes conectados al WebSocket.
    Se llama automáticamente al crear o actualizar un incidente.
    """
    if not WS_ENDPOINT:
        print("WS_ENDPOINT no está definido, no se envía broadcast.")
        return

    # Cliente para API Gateway Management API
    ws_client = boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=WS_ENDPOINT,
    )

    data = connections_table.scan(ProjectionExpression="connectionId")
    items = data.get("Items", [])

    message = json.dumps(
        {
            "type": message_type,
            "payload": payload,
        }
    )

    for item in items:
        connection_id = item["connectionId"]
        try:
            ws_client.post_to_connection(
                ConnectionId=connection_id,
                Data=message.encode("utf-8"),
            )
        except ws_client.exceptions.GoneException:
            # Conexión muerta: la borramos
            print("Conexión muerta, eliminando:", connection_id)
            connections_table.delete_item(Key={"connectionId": connection_id})
        except Exception as e:
            print(f"Error enviando a {connection_id}: {e}")


def crear_incidente(event, context):
    """
    POST /incidentes
    Body JSON:
    {
      "tipo": "infraestructura",
      "ubicacion": "Piso 3, aula 304",
      "descripcion": "Fuga de agua",
      "urgencia": "alta"
    }
    """
    try:
        body = json.loads(event.get("body") or "{}")
        now = datetime.utcnow().isoformat()

        incident_id = str(uuid.uuid4())

        item = {
            "incidentId": incident_id,
            "tipo": body.get("tipo", "otro"),
            "ubicacion": body.get("ubicacion", "desconocida"),
            "descripcion": body.get("descripcion", ""),
            "urgencia": body.get("urgencia", "media"),
            "estado": "pendiente",
            "createdAt": now,
            "updatedAt": now,
            # Aquí podrías agregar createdBy, rol, etc.
        }

        incidents_table.put_item(Item=item)

        # 🔔 Notificar a todos por WebSocket
        _broadcast_ws("INCIDENT_CREATED", item)

        return _response(201, item)
    except Exception as e:
        print("Error en crear_incidente:", e)
        return _response(500, {"error": "Error creando incidente"})


def listar_incidentes(event, context):
    """
    GET /incidentes
    (Por simplicidad, lista todos. Podrías filtrar por estado usando query params)
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
      "estado": "en_atencion",
      "urgencia": "alta",
      "assignedTo": "Mantenimiento"
    }
    """
    try:
        incident_id = event["pathParameters"]["id"]
        body = json.loads(event.get("body") or "{}")

        current = incidents_table.get_item(
            Key={"incidentId": incident_id}
        ).get("Item")

        if not current:
            return _response(404, {"error": "Incidente no encontrado"})

        now = datetime.utcnow().isoformat()

        updated = {
            **current,
            "estado": body.get("estado", current.get("estado", "pendiente")),
            "urgencia": body.get("urgencia", current.get("urgencia", "media")),
            "assignedTo": body.get("assignedTo", current.get("assignedTo")),
            "updatedAt": now,
        }

        incidents_table.put_item(Item=updated)

        # 🔔 Notificar actualización por WebSocket
        _broadcast_ws("INCIDENT_UPDATED", updated)

        return _response(200, updated)
    except Exception as e:
        print("Error en actualizar_incidente:", e)
        return _response(500, {"error": "Error actualizando incidente"})
