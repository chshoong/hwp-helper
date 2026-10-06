"""HWPX(OWPML) XML 네임스페이스."""

NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "opf": "http://www.idpf.org/2007/opf/",
    "ocf": "urn:oasis:names:tc:opendocument:xmlns:container",
}


def q(tag: str) -> str:
    """'hp:p' 같은 접두사 표기를 lxml이 쓰는 '{uri}p' 표기로 바꾼다."""
    prefix, local = tag.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"
