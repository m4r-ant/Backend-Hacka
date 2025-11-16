import json
import os
from datetime import datetime

import boto3

dynamodb = boto3.resource("dynamodb")
CONNECTIONS_TABLE_NAME = os.environ["CONNECTIONS_TABLE"]
connections_table = dynamodb.Table(CONNECTIONS_TABLE_NAME)


def _get_ws_client(event):
    """
    Crea el cliente para API Gateway WebSocket (Management API)
    usando el dominio y stage de la invocación.
    """
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]

    return boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=f"https://{domain}/{stage}",
    )


def connect(event, context):
    connection_id = event["requestContext"]["connectionId"]
    print("WS connect:", connection_id)

    connections_table.put_item(
        Item={
            "connectionId": connection_id,
            "connectedAt": datetime.utcnow().isoformat(),
        }
    )

    return {"statusCode": 200, "body": "Connected"}


def disconnect(event, context):
    connection_id = event["requestContext"]["connectionId"]
    print("WS disconnect:", connection_id)

    connections_table.delete_item(
        Key={"connectionId": connection_id}
    )

    return {"statusCode": 200, "body": "Disconnected"}


def default_handler(event, context):
    print("WS default message:", event.get("body"))
    return {"statusCode": 200, "body": "OK"}


def broadcast(event, context):
    """
    El cliente envía por WebSocket algo como:
    {
      "action": "broadcast",
      "type": "INCIDENT_UPDATED",
      "payload": {
        "incidentId": "...",
        "status": "en_atencion"
      }
    }
    """
    try:
        ws_client = _get_ws_client(event)
        body = json.loads(event.get("body") or "{}")

        message = json.dumps(
            {
                "type": body.get("type", "EVENT"),
                "payload": body.get("payload", {}),
            }
        )

        # Leer todas las conexiones
        scan_res = connections_table.scan(ProjectionExpression="connectionId")
        items = scan_res.get("Items", [])

        for item in items:
            cid = item["connectionId"]
            try:
                ws_client.post_to_connection(
                    ConnectionId=cid,
                    Data=message.encode("utf-8"),
                )
            except ws_client.exceptions.GoneException:
                # Conexión muerta: la borramos
                print("Conexión muerta, eliminando:", cid)
                connections_table.delete_item(Key={"connectionId": cid})
            except Exception as e:
                print("Error enviando a", cid, ":", e)

        return {"statusCode": 200, "body": "Broadcast OK"}
    except Exception as e:
        print("Error en broadcast:", e)
        return {"statusCode": 500, "body": "Error en broadcast"}
