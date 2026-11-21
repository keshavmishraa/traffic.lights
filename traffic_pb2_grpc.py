# gRPC client stubs and server registrations for traffic.proto.
# Included so grpcio-tools/protoc are not required by users.
import grpc
import traffic_pb2 as pb


class CoordinatorStub:
    def __init__(self, channel):
        self.Heartbeat = channel.unary_unary(
            '/junction.Coordinator/Heartbeat',
            request_serializer=pb.LightRequest.SerializeToString,
            response_deserializer=pb.Empty.FromString,
        )
        self.Join = channel.unary_unary(
            '/junction.Coordinator/Join',
            request_serializer=pb.Arrival.SerializeToString,
            response_deserializer=pb.JoinReply.FromString,
        )
        self.RequestPass = channel.unary_unary(
            '/junction.Coordinator/RequestPass',
            request_serializer=pb.VehicleRequest.SerializeToString,
            response_deserializer=pb.Permission.FromString,
        )
        self.Finish = channel.unary_unary(
            '/junction.Coordinator/Finish',
            request_serializer=pb.VehicleRequest.SerializeToString,
            response_deserializer=pb.Ack.FromString,
        )
        self.Status = channel.unary_unary(
            '/junction.Coordinator/Status',
            request_serializer=pb.LightRequest.SerializeToString,
            response_deserializer=pb.LightStatus.FromString,
        )
        self.Snapshot = channel.unary_unary(
            '/junction.Coordinator/Snapshot',
            request_serializer=pb.Empty.SerializeToString,
            response_deserializer=pb.JunctionSnapshot.FromString,
        )


def add_CoordinatorServicer_to_server(servicer, server):
    handlers = {
        'Heartbeat': grpc.unary_unary_rpc_method_handler(
            servicer.Heartbeat,
            request_deserializer=pb.LightRequest.FromString,
            response_serializer=pb.Empty.SerializeToString,
        ),
        'Join': grpc.unary_unary_rpc_method_handler(
            servicer.Join,
            request_deserializer=pb.Arrival.FromString,
            response_serializer=pb.JoinReply.SerializeToString,
        ),
        'RequestPass': grpc.unary_unary_rpc_method_handler(
            servicer.RequestPass,
            request_deserializer=pb.VehicleRequest.FromString,
            response_serializer=pb.Permission.SerializeToString,
        ),
        'Finish': grpc.unary_unary_rpc_method_handler(
            servicer.Finish,
            request_deserializer=pb.VehicleRequest.FromString,
            response_serializer=pb.Ack.SerializeToString,
        ),
        'Status': grpc.unary_unary_rpc_method_handler(
            servicer.Status,
            request_deserializer=pb.LightRequest.FromString,
            response_serializer=pb.LightStatus.SerializeToString,
        ),
        'Snapshot': grpc.unary_unary_rpc_method_handler(
            servicer.Snapshot,
            request_deserializer=pb.Empty.FromString,
            response_serializer=pb.JunctionSnapshot.SerializeToString,
        ),
    }
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler('junction.Coordinator', handlers),
    ))


class TrafficLightStub:
    def __init__(self, channel):
        self.Arrive = channel.unary_unary(
            '/junction.TrafficLight/Arrive',
            request_serializer=pb.Arrival.SerializeToString,
            response_deserializer=pb.JoinReply.FromString,
        )
        self.RequestPass = channel.unary_unary(
            '/junction.TrafficLight/RequestPass',
            request_serializer=pb.VehicleRequest.SerializeToString,
            response_deserializer=pb.Permission.FromString,
        )
        self.Finish = channel.unary_unary(
            '/junction.TrafficLight/Finish',
            request_serializer=pb.VehicleRequest.SerializeToString,
            response_deserializer=pb.Ack.FromString,
        )
        self.Status = channel.unary_unary(
            '/junction.TrafficLight/Status',
            request_serializer=pb.Empty.SerializeToString,
            response_deserializer=pb.LightStatus.FromString,
        )


def add_TrafficLightServicer_to_server(servicer, server):
    handlers = {
        'Arrive': grpc.unary_unary_rpc_method_handler(
            servicer.Arrive,
            request_deserializer=pb.Arrival.FromString,
            response_serializer=pb.JoinReply.SerializeToString,
        ),
        'RequestPass': grpc.unary_unary_rpc_method_handler(
            servicer.RequestPass,
            request_deserializer=pb.VehicleRequest.FromString,
            response_serializer=pb.Permission.SerializeToString,
        ),
        'Finish': grpc.unary_unary_rpc_method_handler(
            servicer.Finish,
            request_deserializer=pb.VehicleRequest.FromString,
            response_serializer=pb.Ack.SerializeToString,
        ),
        'Status': grpc.unary_unary_rpc_method_handler(
            servicer.Status,
            request_deserializer=pb.Empty.FromString,
            response_serializer=pb.LightStatus.SerializeToString,
        ),
    }
    server.add_generic_rpc_handlers((
        grpc.method_handlers_generic_handler('junction.TrafficLight', handlers),
    ))
