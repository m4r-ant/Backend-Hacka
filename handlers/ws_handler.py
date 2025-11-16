# handlers/ws_handler.py
import json
import os

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT")


def _get_apigw_client():
    if not WS_ENDPOINT:
        raise RuntimeError("WS_ENDPOINT no está configurado")

    return boto3.client("apigatewaymanagementapi", endpoint_url=WS_ENDPOINT)


def connect(event, context):
    """
    $connect
    Guarda la conexión en DynamoDB.
    """
    print("WS $connect event:", event)

    connection_id = event["requestContext"]["connectionId"]
    table = dynamodb.Table(CONNECTIONS_TABLE)

    table.put_item(Item={"connectionId": connection_id})

    return {
        "statusCode": 200,
        "body": "Connected.",
    }


def disconnect(event, context):
    """
    $disconnect
    Elimina la conexión de DynamoDB.
    """
    print("WS $disconnect event:", event)

    connection_id = event["requestContext"]["connectionId"]
    table = dynamodb.Table(CONNECTIONS_TABLE)

    table.delete_item(Key={"connectionId": connection_id})

    return {
        "statusCode": 200,
        "body": "Disconnected.",
    }


def default_handler(event, context):
    """
    $default
    Cualquier mensaje que no caiga en una ruta específica.
    """
    print("WS $default event:", event)

    body = event.get("body")
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {"raw": body}

    print("Mensaje recibido por WebSocket:", data)

    return {
        "statusCode": 200,
        "body": "OK",
    }


def broadcast(event, context):
    """
    Ruta 'broadcast' del WebSocket.
    Envía un mensaje a todos los clientes conectados.
    El body puede tener 'message' o cualquier payload.
    """
    print("WS broadcast event:", event)

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        body = {}

    # Mensaje estándar
    payload = {
        "action": body.get("action", "broadcast"),
        "message": body.get("message", "Hola desde broadcast"),
        "data": body.get("data", {}),
    }

    apigw = _get_apigw_client()
    table = dynamodb.Table(CONNECTIONS_TABLE)

    resp = table.scan()
    connections = resp.get("Items", [])

    print(f"Broadcast a {len(connections)} conexiones.")
    data_bytes = json.dumps(payload).encode("utf-8")

    for conn in connections:
        connection_id = conn.get("connectionId")
        if not connection_id:
            continue

        try:
            apigw.post_to_connection(ConnectionId=connection_id, Data=data_bytes)
        except ClientError as e:
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            print(f"Error enviando a {connection_id}:", e)
            if status == 410:
                print(f"Conexión {connection_id} muerta, eliminando.")
                table.delete_item(Key={"connectionId": connection_id})

    return {
        "statusCode": 200,
        "body": "Broadcast enviado.",
    }
