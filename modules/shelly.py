import requests

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import capture_response
from helpers.registry import register_job
from helpers.requirements import Requirement


def _base_url() -> str:
    from helpers.config import Config

    return Config.module_settings("shelly").get("base_url", "http://192.168.18.53")


def _shelly_requirement() -> Requirement:
    return Requirement(
        check=lambda: bool(_base_url()),
        setup_hint="Set modules.shelly.base_url in config.yaml to your Shelly device's IP address.",
    )


@register_job(module_name="shelly", requires=_shelly_requirement())
@capture_response
def turn_light_on() -> str:
    """
    Controls a physical Shelly smart switch/relay device to turn ON a connected light fixture.
    This function sends a HTTP GET request to a specific Shelly device on the local network
    to activate relay 0, which controls the connected lighting circuit.

    Use this function when the user wants to:
    - Turn on lights in a room
    - Activate lighting via smart home control
    - Switch on electrical devices connected to the Shelly relay
    - Enable illumination through voice commands or automation

    Keywords: turn on light, light on, shelly on, turn light on, switch on light, enable light,
             activate light, start light, power on light, illuminate, lighting on

    Returns:
        str: Success confirmation message or detailed error information about the light operation.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.play_cached("Turning light on...")
    print("Turning light on...")

    try:
        response = requests.get(f"{_base_url()}/light/0/?turn=on")

        if response.status_code == 200:
            return "Light turned on successfully."
        else:
            return (
                f"Error: Failed to turn on light. Status code: {response.status_code}"
            )

    except requests.exceptions.RequestException as e:
        print(f"Error turning on light: {e}")
        return "Error: Could not connect to Shelly device to turn on the light."


@register_job(module_name="shelly", requires=_shelly_requirement())
@capture_response
def turn_light_off() -> str:
    """
    Controls a physical Shelly smart switch/relay device to turn OFF a connected light fixture.
    This function sends a HTTP GET request to a specific Shelly device on the local network
    to deactivate relay 0, which controls the connected lighting circuit.

    Use this function when the user wants to:
    - Turn off lights in a room
    - Deactivate lighting via smart home control
    - Switch off electrical devices connected to the Shelly relay
    - Disable illumination through voice commands or automation
    - Save energy by turning off unnecessary lighting

    Keywords: turn off light, light off, shelly off, turn light off, switch off light, disable light,
             deactivate light, stop light, power off light, darken, lighting off, extinguish

    Returns:
        str: Success confirmation message or detailed error information about the light operation.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.play_cached("Turning light off...")
    print("Turning light off...")

    try:
        response = requests.get(f"{_base_url()}/light/0/?turn=off")

        if response.status_code == 200:
            return "Light turned off successfully."
        else:
            return (
                f"Error: Failed to turn off light. Status code: {response.status_code}"
            )

    except requests.exceptions.RequestException as e:
        print(f"Error turning off light: {e}")
        return "Error: Could not connect to Shelly device to turn off the light."


@register_job(module_name="shelly", requires=_shelly_requirement())
@capture_response
def toggle_light() -> str:
    """
    Controls a physical Shelly smart switch/relay device to toggle the light state.
    This function first checks the current state of the light by sending a GET request
    to the Shelly device, then toggles it to the opposite state (on->off or off->on).

    Use this function when the user wants to:
    - Toggle light state without knowing current status
    - Switch light to opposite state
    - Smart toggle functionality in automation
    - Quick light control via voice commands

    Keywords: toggle light, switch light, flip light, change light state, light toggle,
             reverse light, alternate light, flip switch, toggle switch

    Returns:
        str: Success confirmation message with the new state or detailed error information.
    """
    audio = Cache.get_audio()
    if audio:
        Audio.play_cached("Toggling light...")
    print("Toggling light...")

    try:
        status_response = requests.get(f"{_base_url()}/light/0")

        if status_response.status_code != 200:
            return f"Error: Failed to get light status. Status code: {status_response.status_code}"

        status_data = status_response.json()
        current_state = status_data.get("ison", False)

        new_state = "off" if current_state else "on"
        toggle_response = requests.get(f"{_base_url()}/light/0/?turn={new_state}")

        if toggle_response.status_code == 200:
            return f"Light toggled successfully. Light is now {'on' if new_state == 'on' else 'off'}."
        else:
            return f"Error: Failed to toggle light. Status code: {toggle_response.status_code}"

    except requests.exceptions.RequestException as e:
        print(f"Error toggling light: {e}")
        return "Error: Could not connect to Shelly device to toggle the light."
