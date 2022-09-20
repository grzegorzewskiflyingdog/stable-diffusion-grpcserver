import argparse, os, sys
from concurrent import futures

import yaml
try:
    from yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from yaml import Loader, Dumper

import grpc
from waitress import serve
from sonora.wsgi import grpcWSGI
from wsgicors import CORS

# Google protoc compiler is dumb about imports (https://github.com/protocolbuffers/protobuf/issues/1491)
# TODO: Move to https://github.com/danielgtaylor/python-betterproto
generatedPath = os.path.join(os.path.dirname(__file__), "generated")
sys.path.append(generatedPath)

from generated import generation_pb2_grpc, dashboard_pb2_grpc, engines_pb2_grpc

from sdgrpcserver.manager import EngineManager
from sdgrpcserver.services.dashboard import DashboardServiceServicer
from sdgrpcserver.services.generate import GenerationServiceServicer
from sdgrpcserver.services.engines import EnginesServiceServicer

class DartGRPCCompatibility(object):
    """Fixes a couple of compatibility issues between Dart GRPC-WEB and Sonora

    - Dart GRPC-WEB doesn't set HTTP_ACCEPT header, but Sonora needs it to build Content-Type header on response
    - Sonora sets Access-Control-Allow-Origin to HTTP_HOST, and we need to strip it out so CORSWSGI can set the correct value
    """
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        def wrapped_start_response(status, headers):
            headers = [header for header in headers if header[0] != 'Access-Control-Allow-Origin']
            return start_response(status, headers)
        
        if environ.get("HTTP_ACCEPT") == "*/*":
            environ["HTTP_ACCEPT"] = "application/grpc-web+proto"

        return self.app(environ, wrapped_start_response)

def start(manager):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    generation_pb2_grpc.add_GenerationServiceServicer_to_server(GenerationServiceServicer(manager), server)
    dashboard_pb2_grpc.add_DashboardServiceServicer_to_server(DashboardServiceServicer(), server)
    engines_pb2_grpc.add_EnginesServiceServicer_to_server(EnginesServiceServicer(manager), server)

    server.add_insecure_port('[::]:50051')
    server.start()

    grpcapp = wsgi_app = grpcWSGI(None)
    wsgi_app = DartGRPCCompatibility(wsgi_app)
    wsgi_app = CORS(wsgi_app, headers="*", methods="*", origin="*")

    generation_pb2_grpc.add_GenerationServiceServicer_to_server(GenerationServiceServicer(manager), grpcapp)
    dashboard_pb2_grpc.add_DashboardServiceServicer_to_server(DashboardServiceServicer(), grpcapp)
    engines_pb2_grpc.add_EnginesServiceServicer_to_server(EnginesServiceServicer(manager), grpcapp)

    print("Ready, GRPC listening on port 50051, GRPC-Web listening on port 5000")
    serve(wsgi_app, listen="*:5000")

    #This does same thing as app.run
    #server.wait_for_termination()

def main(args):
    with open(os.path.normpath(args.enginecfg), 'r') as cfg:
        engines = yaml.load(cfg, Loader=Loader)
        manager = EngineManager(engines)

        start(manager)

    sys.exit(-1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--enginecfg", "-E", type=str, default="./engines.yaml", help="Path to the engines.yaml file"
    )
    parser.add_argument(
        "--listen_to_all", "-L", type=bool, default=False, help="Accept requests from the local network, not just localhost" 
    )
    args = parser.parse_args()
    main(args)


