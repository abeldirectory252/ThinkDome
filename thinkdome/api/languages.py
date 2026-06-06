"""Language and runtime info endpoints."""

from fastapi import APIRouter, HTTPException

from thinkdome.models.languages import LanguageInfo, PackageInfo, RuntimeInfo

router = APIRouter(tags=["languages"])

# Static language registry
_LANGUAGES: dict[str, LanguageInfo] = {
    "python": LanguageInfo(
        name="python", version="3.12", status="available", extensions=[".py"]
    ),
    "cpp": LanguageInfo(
        name="cpp", version="", status="coming_soon", extensions=[".cpp", ".cc", ".h"]
    ),
    "java": LanguageInfo(
        name="java", version="", status="coming_soon", extensions=[".java"]
    ),
    "csharp": LanguageInfo(
        name="csharp", version="", status="coming_soon", extensions=[".cs"]
    ),
}

_PYTHON_PACKAGES: list[PackageInfo] = [
    PackageInfo(name="numpy", version="latest"),
    PackageInfo(name="pandas", version="latest"),
    PackageInfo(name="matplotlib", version="latest"),
    PackageInfo(name="scipy", version="latest"),
    PackageInfo(name="sympy", version="latest"),
    PackageInfo(name="requests", version="latest"),
    PackageInfo(name="pillow", version="latest"),
    PackageInfo(name="scikit-learn", version="latest"),
    PackageInfo(name="seaborn", version="latest"),
    PackageInfo(name="openpyxl", version="latest"),
    PackageInfo(name="beautifulsoup4", version="latest"),
    PackageInfo(name="pyyaml", version="latest"),
]


@router.get("/languages", response_model=list[LanguageInfo])
async def list_languages():
    """List supported languages."""
    return list(_LANGUAGES.values())


@router.get("/languages/{lang}/packages", response_model=list[PackageInfo])
async def list_packages(lang: str):
    """List pre-installed packages for a language."""
    if lang.lower() not in _LANGUAGES:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found")
    if lang.lower() == "python":
        return _PYTHON_PACKAGES
    return []


@router.post("/languages/{lang}/packages")
async def request_package_install(lang: str):
    """Request a package install (queued)."""
    raise HTTPException(status_code=501, detail="Package install not yet implemented")


@router.get("/runtimes", response_model=list[RuntimeInfo])
async def list_runtimes():
    """List available executor runtimes."""
    return [
        RuntimeInfo(image="thinkdome-executor:latest", language="python", status="ready"),
    ]


@router.post("/runtimes/warmup")
async def warmup_runtimes():
    """Pre-warm executor containers."""
    return {"status": "warmup triggered"}
