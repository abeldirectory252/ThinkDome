"""ORM metadata for FileBox objects."""

from thinkdome.core.orm.orm import Model, StringField, IntegerField, FloatField, SelectField


class FileBoxVolume(Model):
    """Metadata for one encrypted, tenant/user-isolated virtual volume."""
    tenant_id = StringField(required=True)
    owner_id = StringField(required=True)
    volume_name = StringField(default="default")
    container_format = StringField(default="thinkdome-box-v1")
    root_path = StringField(required=True)
    encryption = StringField(default="fernet")
    key_scope = StringField(required=True)
    quota_bytes = IntegerField(default=10 * 1024 * 1024 * 1024)
    used_bytes = IntegerField(default=0)
    status = SelectField(choices=["active", "locked", "deleted"], default="active")
    created_at = StringField(required=True)


class FileBox(Model):
    """A tenant-owned file with explicit temporary or permanent retention."""

    tenant_id = StringField(required=True)
    owner_id = StringField(required=True)
    volume_id = StringField(default="default")
    filename = StringField(required=True)
    folder = StringField(default="workspace")
    storage_path = StringField(required=True)
    retention = SelectField(choices=["temporary", "permanent"], default="temporary")
    expires_at = FloatField(default=0.0)  # 0 means permanent
    size_bytes = IntegerField(default=0)
    sha256 = StringField(default="")
    status = SelectField(choices=["active", "expired", "deleted"], default="active")
    created_at = StringField(required=True)
    deleted_at = StringField(default="")

    @staticmethod
    def _identity(tenant_id=None, owner_id=None):
        if tenant_id and owner_id:
            return str(tenant_id), str(owner_id)
        try:
            from thinkdome.platform.orchestration.tools import get_context
            ctx = get_context()
            identity = getattr(ctx, "identity", None)
            tenant = getattr(identity, "tenant_id", None) if identity else None
            return str(tenant or "default"), str(ctx.username)
        except Exception as exc:
            raise PermissionError("Authenticated tenant and owner are required for FileBox access.") from exc

    @classmethod
    def put(cls, filename, content, *, ttl_seconds=None, ttl=None, permanent=False,
            folder="workspace", override=False, conflict="version", tenant_id=None, owner_id=None):
        """Create an encrypted FileBox owned by the current user."""
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        if isinstance(content, str):
            content = content.encode("utf-8")
        return FileBoxService().create(
            tenant_id=tenant, owner_id=owner, filename=filename,
            content=content, ttl_seconds=ttl_seconds if ttl_seconds is not None else ttl,
            permanent=permanent, folder=folder, override=override, conflict=conflict,
        )

    @classmethod
    def upload(cls, filename, content, **kwargs):
        """Alias for :meth:`put` for upload-oriented callers."""
        return cls.put(filename, content, **kwargs)

    @classmethod
    def get(cls, filebox_id, *, tenant_id=None, owner_id=None):
        """Read a FileBox only when it belongs to the authenticated owner."""
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        result = FileBoxService().read(filebox_id, tenant_id=tenant, owner_id=owner)
        if result is None:
            return None
        content, metadata = result
        metadata._values["content"] = content
        return metadata

    @classmethod
    def list(cls, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().list(tenant_id=tenant, owner_id=owner)

    @classmethod
    def folders(cls, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return list(FileBoxService().ensure_layout(tenant_id=tenant, owner_id=owner).keys())

    @classmethod
    def volume(cls, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        volume = FileBoxService().get_volume(tenant_id=tenant, owner_id=owner)
        return volume.to_dict() if volume else None

    @classmethod
    def exists(cls, filebox_id, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().exists(filebox_id, tenant_id=tenant, owner_id=owner)

    @classmethod
    def delete(cls, filebox_id, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().delete(filebox_id, tenant_id=tenant, owner_id=owner)

    @classmethod
    def renew(cls, filebox_id, ttl_seconds, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().renew(filebox_id, tenant_id=tenant, owner_id=owner, ttl_seconds=ttl_seconds)

    @classmethod
    def permanent(cls, filebox_id, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().make_permanent(filebox_id, tenant_id=tenant, owner_id=owner)

    @classmethod
    def copy(cls, filebox_id, filename, *, tenant_id=None, owner_id=None):
        from .service import FileBoxService
        tenant, owner = cls._identity(tenant_id, owner_id)
        return FileBoxService().copy(filebox_id, tenant_id=tenant, owner_id=owner, filename=filename)
