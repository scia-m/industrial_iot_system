import argparse
import os
import sys

import paho.mqtt.client as mqtt

from gateway.database import GatewayDatabase
from gateway.mqtt.service import MQTTGatewayService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the gateway MQTT service")
    parser.add_argument("--broker", default=os.getenv("MQTT_BROKER", "localhost"), help="MQTT broker host")
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")), help="MQTT broker port")
    parser.add_argument("--client-id", default=os.getenv("MQTT_CLIENT_ID", "gateway-mqtt-service"), help="MQTT client ID")
    parser.add_argument("--username", default=os.getenv("MQTT_USERNAME"), help="MQTT username")
    parser.add_argument("--password", default=os.getenv("MQTT_PASSWORD"), help="MQTT password")
    parser.add_argument("--keepalive", type=int, default=int(os.getenv("MQTT_KEEPALIVE", "60")), help="MQTT keepalive interval")
    parser.add_argument(
        "--topics",
        nargs="*",
        default=os.getenv("MQTT_TOPICS", "factory/+/telemetry factory/+/heartbeat factory/+/status").split(),
        help="Topics to subscribe to",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = GatewayDatabase(os.getenv("GATEWAY_DB_PATH", "gateway/gateway.db"))
    service = MQTTGatewayService(db=db)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.client_id)
    if args.username is not None:
        client.username_pw_set(args.username, args.password)

    def on_connect(client: mqtt.Client, userdata: object, flags: dict, reason_code: int, properties: object) -> None:
        if reason_code != 0:
            print(f"MQTT connection failed: {reason_code}", file=sys.stderr)
            sys.exit(1)
        for topic in args.topics:
            client.subscribe(topic)
        print(f"Connected to {args.broker}:{args.port} and subscribed to {', '.join(args.topics)}")

    def on_message(client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        service.handle_message(msg.topic, payload)

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(args.broker, args.port, keepalive=args.keepalive)
        client.loop_forever()
    except KeyboardInterrupt:
        print("Stopping MQTT service")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
