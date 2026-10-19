"""Bring a model in from a link: a Printables page, or a file's own URL.

What each site allows decides what this can do, so a link is sorted before
anything is fetched:

* **Printables** gives any model's files to anyone, through the same
  GraphQL calls its own Download button makes: one query lists the model's
  files, one mutation hands out each file's link. Every model file
  (STL, 3MF, STEP, OBJ, AMF) is brought in, into a folder named after it.
* **A direct link** to a model file is downloaded as it is.
* **MakerWorld** (what Bambu Handy shares) answers a download with "Please
  log in to download models" from behind a browser challenge, so a server
  cannot fetch from it on anybody's behalf. The refusal says where it does
  work: Bambu Studio's own MakerWorld page in the Studio tab, signed in
  with the person's Bambu account.
* **Thingiverse** needs a developer key; the refusal says to use the file's
  own link.

Everything lands under /share/bambu/imports through `library`, whose name
checks every file name goes through. Redirects are followed only to http(s).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import library

IMPORTS = "imports"
TIMEOUT = 60
MAX_FILES = 40
UA = "Mozilla/5.0 (X11; Linux x86_64) BRUH-Bambu-Studio"
PRINTABLES_API = "https://api.printables.com/graphql/"
PRINTABLES_HOST = re.compile(r"^(?:www\.)?printables\.com$", re.IGNORECASE)
PRINTABLES_ID = re.compile(r"/model/(\d+)")
MAKERWORLD_HOST = re.compile(r"(?:^|\.)(?:makerworld\.com|bambulab\.com|bambulab\.cn)$",
                             re.IGNORECASE)
THINGIVERSE_HOST = re.compile(r"(?:^|\.)thingiverse\.com$", re.IGNORECASE)

MAKERWORLD_REFUSAL = (
    "MakerWorld only gives a model to a signed-in Bambu account, so the add-on "
    "cannot fetch it for you. Open the Studio tab, sign in on Bambu Studio's "
    "MakerWorld page and open the model there — it goes straight into the "
    "slicer — or download it from MakerWorld and upload it on the Files tab.")
THINGIVERSE_REFUSAL = (
    "Thingiverse only gives files to apps with a Thingiverse key. Open the "
    "model's Files list, copy the link of the STL itself and paste that here.")


class Refused(ValueError):
    """A link this will not import, with the sentence that says why."""


class _HttpOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to http(s): the standard library would also
    follow one to ftp://, and says nothing useful about a file:// one."""

    def http_error_302(self, req, fp, code, msg, headers):
        target = headers.get("location") or headers.get("uri") or ""
        if urllib.parse.urlsplit(urllib.parse.urljoin(req.full_url, target)).scheme not in (
                "http", "https"):
            raise Refused("That link redirects somewhere that is not a web address.")
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


_OPENER = urllib.request.build_opener(_HttpOnlyRedirects)


def _open(url: str, data: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    return _OPENER.open(request, timeout=TIMEOUT)


def folder_name(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ._-]+", "", str(title or "")).strip(" .-")
    return re.sub(r"\s+", " ", cleaned)[:60] or "import"


def _model_file(name: str) -> bool:
    return str(name or "").lower().endswith(library.SUFFIXES)


def plan(url: str) -> dict:
    """Sort a link into what will be fetched: {source, title, folder, files}."""
    url = str(url or "").strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise Refused("Paste a web link (https://…) to a model or a model file.")
    host = (parts.hostname or "").lower()
    if MAKERWORLD_HOST.search(host):
        raise Refused(MAKERWORLD_REFUSAL)
    if THINGIVERSE_HOST.search(host):
        raise Refused(THINGIVERSE_REFUSAL)
    if PRINTABLES_HOST.match(host):
        match = PRINTABLES_ID.search(parts.path)
        if not match:
            raise Refused("That Printables link is not a model page (…/model/12345-…).")
        return _printables(match.group(1))
    name = os.path.basename(urllib.parse.unquote(parts.path))
    return {"source": "link", "title": name or host, "folder": "",
            "files": [{"name": name, "url": url}]}


def _graphql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    with _open(PRINTABLES_API, body, {"Content-Type": "application/json"}) as response:
        data = json.loads(response.read(4 << 20))
    if data.get("errors"):
        raise Refused(f"Printables refused: {data['errors'][0].get('message', 'unknown error')}")
    return data.get("data") or {}


def _printables(model_id: str) -> dict:
    data = _graphql("query M($id: ID!){ print(id:$id){ id name stls{ id name } } }",
                    {"id": model_id})
    model = data.get("print")
    if not model:
        raise Refused(f"Printables has no model {model_id}.")
    files = [{"name": f["name"], "printables_id": f["id"]}
             for f in model.get("stls") or [] if _model_file(f.get("name"))]
    if not files:
        raise Refused(f"“{model.get('name')}” on Printables has no STL, 3MF or STEP files.")
    return {"source": "printables", "title": model.get("name") or model_id,
            "folder": folder_name(model.get("name") or model_id), "model_id": model_id,
            "files": files[:MAX_FILES], "skipped": max(0, len(files) - MAX_FILES)}


def _printables_link(model_id: str, file_id: str) -> str:
    data = _graphql(
        "mutation D($id: ID!, $printId: ID!){ getDownloadLink(id:$id, printId:$printId, "
        "fileType: stl, source: model_detail){ ok errors{ messages } output{ link } } }",
        {"id": file_id, "printId": model_id})
    out = data.get("getDownloadLink") or {}
    link = (out.get("output") or {}).get("link")
    if not out.get("ok") or not link:
        raise Refused("Printables would not give a download link for that file.")
    return link


def _filename(response, fallback: str) -> str:
    disposition = response.headers.get("Content-Disposition") or ""
    match = (re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.IGNORECASE)
             or re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE))
    name = urllib.parse.unquote(match.group(1)) if match else fallback
    return os.path.basename(name.replace("\\", "/")).strip()


def _download(url: str, name: str, folder: Path, progress=None) -> Path:
    with _open(url) as response:
        name = _filename(response, name)
        kind = (response.headers.get("Content-Type") or "").lower()
        if not _model_file(name):
            if "html" in kind:
                raise Refused("That link opens a web page, not a model file. Copy the "
                              "link of the download itself (it ends in .stl or .3mf).")
            raise Refused(f"“{name or url}” is not a model file this can print "
                          "(.3mf, .stl, .step, .obj or .amf).")
        name = library.safe_upload_name(name)
        folder.mkdir(parents=True, exist_ok=True)
        dest = library.unique(folder / name)
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        try:
            with open(dest, "wb") as out:
                while block := response.read(1 << 20):
                    done += len(block)
                    if done > library.MAX_UPLOAD:
                        raise Refused("That file is over 512 MB.")
                    out.write(block)
                    if progress:
                        progress(done, total)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    return dest


def run(job: dict, url: str) -> None:
    """Blocking: plan, then download every file; updates `job` throughout."""
    try:
        job["phase"] = "looking"
        found = plan(url)
        job.update(title=found["title"], source=found["source"])
        base = library.path_of(IMPORTS)
        folder = library.path_of(f"{IMPORTS}/{found['folder']}") if found["folder"] else base
        saved = []
        for i, item in enumerate(found["files"], 1):
            job["phase"] = f"downloading {i} of {len(found['files'])}"
            link = (_printables_link(found["model_id"], item["printables_id"])
                    if found["source"] == "printables" else item["url"])
            dest = _download(link, item["name"], folder,
                             lambda d, t: job.update(progress=round(d / t * 100) if t else None))
            saved.append(library.relative(dest))
        job.update(state="done", phase="done", files=saved, progress=None,
                   skipped=found.get("skipped", 0))
    except Refused as exc:
        job.update(state="failed", error=str(exc))
    except urllib.error.HTTPError as exc:
        job.update(state="failed", error=f"The site answered {exc.code} {exc.reason}.")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or exc
        job.update(state="failed", error=f"Could not download it: {reason}")
    finally:
        job["finished"] = time.time()
