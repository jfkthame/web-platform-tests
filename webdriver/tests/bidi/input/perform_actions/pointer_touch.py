import pytest

from webdriver.bidi.error import MoveTargetOutOfBoundsException, NoSuchFrameException
from webdriver.bidi.modules.input import Actions, get_element_origin
from webdriver.bidi.modules.script import ContextTarget

from .. import get_events
from . import (
    assert_pointer_events,
    get_inview_center_bidi,
    get_shadow_root_from_test_page,
    record_pointer_events,
)

pytestmark = pytest.mark.asyncio

CONTEXT_LOAD_EVENT = "browsingContext.load"


async def test_click_at_fractional_coordinates(bidi_session, top_context, inline):
    url = inline("""
        <script>
          var allEvents = { events: [] };
          window.addEventListener("pointermove", ev => {
            allEvents.events.push({
                "type": event.type,
                "pageX": event.pageX,
                "pageY": event.pageY,
            });
          }, { once: true });
        </script>
        """)

    await bidi_session.browsing_context.navigate(
        context=top_context["context"],
        url=url,
        wait="complete",
    )

    target_point = {
        "x": 5.75,
        "y": 10.25,
    }

    actions = Actions()
    (
        actions
        .add_pointer(pointer_type="touch")
        .pointer_down(button=0)
        .pointer_move(x=target_point["x"], y=target_point["y"])
    )

    await bidi_session.input.perform_actions(
        actions=actions, context=top_context["context"]
    )

    events = await get_events(bidi_session, top_context["context"])
    assert len(events) == 1

    # For now we are allowing any of floor, ceil, or precise values, because
    # it's unclear what the actual spec requirements really are
    assert events[0]["type"] == "pointermove"
    assert events[0]["pageX"] == pytest.approx(target_point["x"], abs=1.0)
    assert events[0]["pageY"] == pytest.approx(target_point["y"], abs=1.0)


async def test_pointer_down_closes_browsing_context(
    bidi_session, configuration, get_element, new_tab, inline, subscribe_events,
    wait_for_event
):
    url = inline("""<input onpointerdown="window.close()">close</input>""")

    # Opening a new context via `window.open` is required for script to be able
    # to close it.
    await subscribe_events(events=[CONTEXT_LOAD_EVENT])
    on_load = wait_for_event(CONTEXT_LOAD_EVENT)

    await bidi_session.script.evaluate(
        expression=f"window.open('{url}')",
        target=ContextTarget(new_tab["context"]),
        await_promise=True
    )
    # Wait for the new context to be created and get it.
    new_context = await on_load

    element = await get_element("input", context=new_context)
    origin = get_element_origin(element)

    actions = Actions()
    (
        actions.add_pointer(pointer_type="touch")
        .pointer_move(0, 0, origin=origin)
        .pointer_down(button=0)
        .pause(250 * configuration["timeout_multiplier"])
        .pointer_up(button=0)
    )

    with pytest.raises(NoSuchFrameException):
        await bidi_session.input.perform_actions(
            actions=actions, context=new_context["context"]
        )


@pytest.mark.parametrize("origin", ["element", "pointer", "viewport"])
async def test_params_actions_origin_outside_viewport(
    bidi_session, get_actions_origin_page, top_context, get_element, origin
):
    if origin == "element":
        url = get_actions_origin_page(
            """width: 100px; height: 50px; background: green;
            position: relative; left: -200px; top: -100px;"""
        )
        await bidi_session.browsing_context.navigate(
            context=top_context["context"],
            url=url,
            wait="complete",
        )

        element = await get_element("#inner")
        origin = get_element_origin(element)

    actions = Actions()
    (
        actions.add_pointer(pointer_type="touch")
        .pointer_move(x=-100, y=-100, origin=origin)
    )

    with pytest.raises(MoveTargetOutOfBoundsException):
        await bidi_session.input.perform_actions(
            actions=actions, context=top_context["context"]
        )


@pytest.mark.parametrize("mode", ["open", "closed"])
@pytest.mark.parametrize("nested", [False, True], ids=["outer", "inner"])
async def test_touch_pointer_in_shadow_tree(
    bidi_session, top_context, get_test_page, mode, nested
):
    await bidi_session.browsing_context.navigate(
        context=top_context["context"],
        url=get_test_page(
            shadow_doc="""
            <div id="pointer-target"
                 style="width: 10px; height: 10px; background-color:blue;">
            </div>""",
            shadow_root_mode=mode,
            nested_shadow_dom=nested,
        ),
        wait="complete",
    )

    shadow_root = await get_shadow_root_from_test_page(
        bidi_session, top_context, nested
    )

    # Add a simplified event recorder to track events in the test ShadowRoot.
    target = await record_pointer_events(
        bidi_session, top_context, shadow_root, "#pointer-target"
    )

    actions = Actions()
    (
        actions.add_pointer(pointer_type="touch")
        .pointer_move(x=0, y=0, origin=get_element_origin(target))
        .pointer_down(button=0)
        .pointer_up(button=0)
    )

    await bidi_session.input.perform_actions(
        actions=actions, context=top_context["context"]
    )

    await assert_pointer_events(
        bidi_session,
        top_context,
        expected_events=["pointerdown", "pointerup"],
        target="pointer-target",
        pointer_type="touch",
    )


async def test_touch_pointer_properties(
    bidi_session, top_context, get_element, load_static_test_page
):
    await load_static_test_page(page="test_actions_pointer.html")

    pointerArea = await get_element("#pointerArea")
    center = await get_inview_center_bidi(
        bidi_session, context=top_context, element=pointerArea
    )

    actions = Actions()
    (
        actions.add_pointer(pointer_type="touch")
        .pointer_move(x=0, y=0, origin=get_element_origin(pointerArea))
        .pointer_down(
            button=0,
            width=23,
            height=31,
            pressure=0.78,
            twist=355,
        )
        .pointer_move(
            x=10,
            y=10,
            origin=get_element_origin(pointerArea),
            width=39,
            height=35,
            pressure=0.91,
            twist=345,
        )
        .pointer_up(button=0)
        .pointer_move(x=80, y=50, origin=get_element_origin(pointerArea))
    )

    await bidi_session.input.perform_actions(
        actions=actions, context=top_context["context"]
    )

    events = await get_events(bidi_session, top_context["context"])
    # Filter mouse events.
    events = [e for e in events if e["pointerType"] == "touch"]

    assert len(events) == 7
    event_types = [e["type"] for e in events]
    assert [
        "pointerover",
        "pointerenter",
        "pointerdown",
        "pointermove",
        "pointerup",
        "pointerout",
        "pointerleave",
    ] == event_types
    assert events[2]["type"] == "pointerdown"
    assert events[2]["pageX"] == pytest.approx(center["x"], abs=1.0)
    assert events[2]["pageY"] == pytest.approx(center["y"], abs=1.0)
    assert events[2]["target"] == "pointerArea"
    assert events[2]["pointerType"] == "touch"
    assert round(events[2]["width"], 2) == 23
    assert round(events[2]["height"], 2) == 31
    assert round(events[2]["pressure"], 2) == 0.78
    assert events[3]["type"] == "pointermove"
    assert events[3]["pageX"] == pytest.approx(center["x"] + 10, abs=1.0)
    assert events[3]["pageY"] == pytest.approx(center["y"] + 10, abs=1.0)
    assert events[3]["target"] == "pointerArea"
    assert events[3]["pointerType"] == "touch"
    assert round(events[3]["width"], 2) == 39
    assert round(events[3]["height"], 2) == 35
    assert round(events[3]["pressure"], 2) == 0.91


async def test_touch_pointer_properties_angle_twist(
    bidi_session, top_context, get_element, load_static_test_page
):
    await load_static_test_page(page="test_actions_pointer.html")

    pointerArea = await get_element("#pointerArea")
    await get_inview_center_bidi(
        bidi_session, context=top_context, element=pointerArea
    )

    actions = Actions()
    (
        actions.add_pointer(pointer_type="touch")
        .pointer_move(x=0, y=0, origin=get_element_origin(pointerArea))
        .pointer_down(
            button=0,
            width=23,
            height=31,
            pressure=0.78,
            altitude_angle=1.2,
            azimuth_angle=6,
            twist=355,
        )
        .pointer_move(
            x=10,
            y=10,
            origin=get_element_origin(pointerArea),
            width=39,
            height=35,
            pressure=0.91,
            altitude_angle=0.5,
            azimuth_angle=1.8,
            twist=345,
        )
        .pointer_up(button=0)
        .pointer_move(x=80, y=50, origin=get_element_origin(pointerArea))
    )

    await bidi_session.input.perform_actions(
        actions=actions, context=top_context["context"]
    )

    events = await get_events(bidi_session, top_context["context"])
    # Filter mouse events.
    events = [e for e in events if e["pointerType"] == "touch"]

    assert len(events) == 7
    event_types = [e["type"] for e in events]
    assert [
        "pointerover",
        "pointerenter",
        "pointerdown",
        "pointermove",
        "pointerup",
        "pointerout",
        "pointerleave",
    ] == event_types
    assert events[2]["type"] == "pointerdown"
    assert events[2]["tiltX"] == 20
    assert events[2]["tiltY"] == -6
    assert events[2]["twist"] == 355
    assert events[3]["type"] == "pointermove"
    assert events[3]["tiltX"] == -23
    assert events[3]["tiltY"] == 61
    assert events[3]["twist"] == 345
