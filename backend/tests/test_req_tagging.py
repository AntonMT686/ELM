"""Requirements tagged in documents: tag format per source, scan of a Word document (sections, existing tags, "shall"
statements), import with links to document and section, tags written back as a new document iteration, re-scan."""
from __future__ import annotations

import io
import json
import zipfile

API = "/api/v1"

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')


def _p(text, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _docx(paras: list[str]) -> bytes:
    body = "".join(paras)
    xml = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr/></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_tag_requirements_from_a_word_document(client_factory):
    pe = client_factory("pe.kumar")
    project = next(p for p in pe.get(f"{API}/projects").json() if p["code"] == "ALPHA")["id"]
    types = {t["code"]: t for t in pe.get(f"{API}/document-types").json()}
    item = next(i for i in pe.get(f"{API}/projects/{project}/tree").json()["items"] if i["code"] == "CTL-CPU")
    doc = pe.post(f"{API}/documents", data={"meta": json.dumps({"type_id": types["SRS"]["id"], "title": "CPU software requirements (tagging test)", "project_id": project, "item_id": item["id"], "from_template": False})}).json()
    data = _docx([
        _p("3 Functional requirements", "Heading1"),
        _p("3.1 Start-up", "Heading2"),
        _p("The unit shall complete its start-up self-test within 2 s."),
        _p("Background text that is not a requirement."),
        _p("[ALPHA-CTL-CPU-SRS-007] The unit shall log every detected fault with a time stamp."),
        _p("3.2 Interfaces", "Heading2"),
        '<w:tbl><w:tr><w:tc>' + _p("The unit must report its health every 100 ms.") + '</w:tc></w:tr></w:tbl>',
    ])
    up = pe.post(f"{API}/documents/{doc['id']}/content", files={"file": ("srs.docx", data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert up.status_code == 200, up.text

    bad = pe.post(f"{API}/projects/{project}/requirement-sources", json={"name": "Bad format", "key_prefix": "BADX", "tag_format": "{PREFIX}-{FOO}"})
    assert bad.json()["error"]["code"] == "TAG_FORMAT"
    src = pe.post(f"{API}/projects/{project}/requirement-sources", json={"name": "CPU SRS (tagging)", "key_prefix": "CPU-SRS", "tag_format": "{PROJECT}-{ITEM}-SRS-{SEQ:3}", "document_id": doc["id"]}).json()
    scan = pe.post(f"{API}/requirement-sources/{src['id']}/document-scan", json={"detect": "both"}).json()
    assert scan["example"].startswith("ALPHA-") and scan["example"].endswith("-SRS-001")
    rows = scan["items"]
    assert [r["state"] for r in rows] == ["new", "new", "new"]
    assert rows[0]["section"] == "3.1 Start-up" and rows[0]["tag"] is None
    assert rows[1]["tag"] == "ALPHA-CTL-CPU-SRS-007" and not rows[1]["text"].startswith("[")
    assert rows[2]["section"] == "3.2 Interfaces", "paragraphs inside tables are read too"
    only_tags = pe.post(f"{API}/requirement-sources/{src['id']}/document-scan", json={"detect": "tags"}).json()["items"]
    assert [r["tag"] for r in only_tags] == ["ALPHA-CTL-CPU-SRS-007"]

    imp = pe.post(f"{API}/requirement-sources/{src['id']}/document-import", json={"paragraphs": [r["paragraph"] for r in rows], "item_id": item["id"], "write_tags": True}).json()
    assert len(imp["created"]) == 3 and "ALPHA-CTL-CPU-SRS-007" in imp["created"]
    assert imp["tags_written"]["written"] and imp["tags_written"]["count"] == 2
    new_keys = sorted(k for k in imp["created"] if k != "ALPHA-CTL-CPU-SRS-007")
    assert new_keys == ["ALPHA-CTL-CPU-SRS-001", "ALPHA-CTL-CPU-SRS-008"], "generated in document order; the hand-written 007 moves the counter on"

    again = pe.post(f"{API}/requirement-sources/{src['id']}/document-scan", json={"detect": "both"}).json()
    assert [r["state"] for r in again["items"]] == ["unchanged"] * 3, "the tags are now in the document"
    assert sorted(r["tag"] for r in again["items"]) == sorted(imp["created"])
    assert again["document"]["iteration"] == 2, "written back as a new iteration, the original is kept"

    reqs = {r["key"]: r for r in pe.get(f"{API}/projects/{project}/requirements", params={"source_id": src["id"]}).json()["items"]}
    det = pe.get(f"{API}/requirements/{reqs['ALPHA-CTL-CPU-SRS-007']['id']}").json()
    assert det["documents"][0]["section"] == "3.1 Start-up" and det["item_id"] == item["id"]
    nxt = pe.post(f"{API}/projects/{project}/requirements", json={"title": "A requirement created by hand", "source_id": src["id"], "item_id": item["id"]}).json()
    assert nxt["key"] == "ALPHA-CTL-CPU-SRS-009", "requirements created by hand use the same tag format and counter"
