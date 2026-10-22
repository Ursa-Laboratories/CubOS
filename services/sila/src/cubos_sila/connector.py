"""SiLA lifecycle and HTTP-only delegation to the CubOS runtime."""

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig
from unitelabs.cdk.config.connector_base_config import DiscoveryConfig
from unitelabs.cdk.features.core.connection_configuration_service import ConnectionConfigurationService

from . import __version__
from .backend import CubOSBackend
from .config import Settings
from .features import CubStatus, ProtocolExecution, RunResults


class CubOSConnector(Connector):
    def __init__(self, settings: Settings, *, backend: CubOSBackend | None = None):
        self.settings = settings
        config = ConnectorBaseConfig(
            sila_server=SiLAServerConfig(
                uuid=settings.server_uuid,
                name=settings.server_name,
                type="CubOS",
                description="CubOS appliance protocols, runtime status, and persisted run results.",
                vendor_url="https://github.com/Ursa-Laboratories/CubOS",
                version=__version__,
                hostname=settings.host,
                port=settings.port,
                tls=settings.certificate is not None,
                certificate_chain=settings.certificate,
                private_key=settings.private_key,
            ),
            discovery=DiscoveryConfig() if settings.discovery else None,
        )
        super().__init__(config)
        self.backend = backend if backend is not None else CubOSBackend(settings)
        self.register(CubStatus(self.backend))
        self.register(ProtocolExecution(self.backend, settings.poll_interval_s))
        self.register(RunResults(self.backend))

    def register(self, feature) -> None:
        # This deployment supports inbound connections only.
        if not isinstance(feature, ConnectionConfigurationService):
            super().register(feature)

    async def stop(self) -> None:
        try:
            await super().stop()
        finally:
            await self.backend.aclose()


def create_app(settings: Settings) -> CubOSConnector:
    return CubOSConnector(settings)
