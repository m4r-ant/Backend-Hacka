# handlers/ws_handler.py

import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")

CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE")


def connect(event, context):
    """
    $connect: guarda la conexión en DynamoDB.
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
    $disconnect: borra la conexión de DynamoDB.
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
    $default: cualquier mensaje que llegue por WS.
    Solo lo logueamos.
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
