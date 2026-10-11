"""E5-R7 regression tests: Naukri application-container detection.

Verifies that the conversational apply drawer (chatbot_Drawer) is detected as
an application surface, that the Apply-button wrapper is NOT mistaken for a
form (false-positive guard), and that legacy dialog detection still works.
"""
import pytest

from backend.services.naukri.adapter import NaukriAdapter


class FakeElement:
    def __init__(self, tag="div", cls="", el_id="", attrs=None, children=None,
                 visible=True):
        self.tag = tag
        self.attrs = dict(attrs or {})
        if cls:
            self.attrs["class"] = cls
        if el_id:
            self.attrs["id"] = el_id
        self.children = list(children or [])
        self._visible = visible

    async def is_visible(self):
        return self._visible

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def query_selector(self, selector):
        for child in self.children:
            if _matches(child, selector):
                return child
        return None

    async def query_selector_all(self, selector):
        return [c for c in self.children if _matches(c, selector)]


def _matches(el: FakeElement, selector: str) -> bool:
    sel = selector.strip()
    if sel == "input[type='radio']" or sel == 'input[type="radio"]':
        return el.tag == "input" and el.attrs.get("type") == "radio"
    if sel.startswith("input"):
        return el.tag == "input"
    if sel in ("textarea", "select", "form"):
        return el.tag == sel
    if sel == 'button[type="submit"]':
        return el.tag == "button" and el.attrs.get("type") == "submit"
    if sel.startswith("."):
        return sel[1:] in (el.attrs.get("class") or "").split()
    if sel.startswith("#"):
        return sel[1:] == el.attrs.get("id")
    return False


class FakePage:
    def __init__(self, selector_map):
        self.selector_map = selector_map

    async def query_selector_all(self, selector):
        return self.selector_map.get(selector, [])


@pytest.fixture
def adapter():
    return NaukriAdapter(browser_type="chrome")


def _radio(value, el_id):
    return FakeElement(tag="input", attrs={"type": "radio", "id": el_id, "value": value})


class TestE5R7ContainerDetection:
    @pytest.mark.asyncio
    async def test_conversational_drawer_detected(self, adapter):
        drawer = FakeElement(
            cls="chatbot_Drawer chatbot_right",
            children=[_radio("Yes", "Yes"), _radio("No", "No")],
        )
        page = FakePage({".chatbot_Drawer": [drawer]})
        result = await adapter._get_visible_application_container(page)
        assert result is drawer

    @pytest.mark.asyncio
    async def test_apply_button_wrapper_is_not_a_form(self, adapter):
        # The Apply button wrapper class contains "apply" but is NOT a form.
        apply_btn = FakeElement(tag="button", el_id="apply-button",
                                attrs={"class": "styles_apply-button__uJI3A apply-button"})
        wrapper = FakeElement(
            cls="styles_jhc__apply-button-container__5Bqnb",
            children=[apply_btn],
        )
        page = FakePage({".chatbot_Drawer": [wrapper],
                         '[class*="chatbot_Drawer"]': [wrapper]})
        result = await adapter._get_visible_application_container(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_candidates_returns_none(self, adapter):
        page = FakePage({})
        result = await adapter._get_visible_application_container(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_legacy_dialog_still_detected(self, adapter):
        dialog = FakeElement(attrs={"role": "dialog"},
                             children=[FakeElement(tag="input",
                                                   attrs={"type": "text"})])
        page = FakePage({'[role="dialog"]': [dialog]})
        result = await adapter._get_visible_application_container(page)
        assert result is dialog

    @pytest.mark.asyncio
    async def test_empty_chatbot_drawer_rejected(self, adapter):
        # A chatbot drawer with no input surface is not an application form.
        drawer = FakeElement(cls="chatbot_Drawer chatbot_right", children=[])
        page = FakePage({".chatbot_Drawer": [drawer]})
        result = await adapter._get_visible_application_container(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_looks_like_application_form_guards(self, adapter):
        wrapper = FakeElement(cls="styles_jhc__apply-button-container__5Bqnb")
        assert await adapter._looks_like_application_form(wrapper) is False

        drawer = FakeElement(cls="chatbot_Drawer",
                             children=[_radio("Yes", "Yes")])
        assert await adapter._looks_like_application_form(drawer) is True

        empty = FakeElement(cls="chatbot_Drawer")
        assert await adapter._looks_like_application_form(empty) is False
