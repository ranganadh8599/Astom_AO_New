"""Photography exposure agent: the triangle, metering and depth of field."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "photography-exposure",
    skills=(
        Skill(
            id="triangle",
            name="The exposure triangle",
            description=(
                "Aperture, shutter speed and ISO, stop arithmetic and equivalent exposures."
            ),
            tags=("aperture", "shutter", "iso"),
            keywords=(
                "aperture", "shutter", "speed", "iso", "exposure", "stop", "stops", "f-stop",
                "fstop", "expose", "underexposed", "overexposed", "brightness", "triangle",
            ),
            text=(
                "One stop is a doubling or halving of light: f/2.8 to f/4, 1/125 to 1/250, or "
                "ISO 100 to 200 each change exposure by one stop. Equivalent exposures keep "
                "brightness constant while changing the look, so f/2.8 at 1/500 is the same "
                "light as f/5.6 at 1/125 if the ISO is unchanged. Raise ISO last, and prefer "
                "widening the aperture or slowing the shutter when depth of field or motion "
                "blur matters more."
            ),
        ),
        Skill(
            id="metering",
            name="Metering and histograms",
            description=(
                "Matrix, centre-weighted and spot metering, highlight clipping and exposing to "
                "the right."
            ),
            tags=("metering", "histogram", "clipping"),
            keywords=(
                "meter", "metering", "matrix", "evaluative", "centre", "weighted", "spot",
                "histogram", "clip", "clipping", "highlight", "shadow", "ettr", "exposure",
                "compensation", "zebra",
            ),
            text=(
                "Matrix metering averages the scene and is right most of the time; "
                "centre-weighted suits portraits with a bright background; spot metering is for "
                "backlit or high-contrast subjects where you meter the face or a mid-grey "
                "target. The histogram describes the captured file, so keep the highlights "
                "just short of the right edge (expose to the right) and recover shadows later. "
                "Blinking highlights and zebras warn before clipping is unrecoverable."
            ),
        ),
        Skill(
            id="depth-of-field",
            name="Depth of field",
            description=(
                "How aperture, focal length and subject distance control the zone of sharpness."
            ),
            tags=("depth-of-field", "bokeh", "hyperfocal"),
            keywords=(
                "depth", "field", "dof", "bokeh", "blur", "background", "sharp", "focal",
                "length", "hyperfocal", "focus", "landscape", "portrait", "macro", "crop",
            ),
            text=(
                "Depth of field shrinks as the aperture widens, the focal length grows and the "
                "subject gets closer. A head-and-shoulders portrait at 85 mm and f/1.8 has "
                "centimetres of sharpness; a landscape at 16 mm and f/11 has metres. Focus "
                "roughly one third into the scene for landscapes, or use the hyperfocal "
                "distance to maximise near-to-far sharpness. A smaller sensor gives more depth "
                "of field at the same framing and aperture."
            ),
        ),
    ),
)
