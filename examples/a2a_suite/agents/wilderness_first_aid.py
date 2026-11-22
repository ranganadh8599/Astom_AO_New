"""Wilderness first aid agent: hypothermia, fractures and evacuation."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "wilderness-first-aid",
    skills=(
        Skill(
            id="hypothermia",
            name="Hypothermia",
            description=(
                "Recognising the stages, insulating and rewarming, and why rapid rewarming is "
                "reserved for hospital care."
            ),
            tags=("hypothermia", "cold", "rewarming"),
            keywords=(
                "hypothermia", "cold", "shiver", "shivering", "rewarm", "rewarming",
                "insulate", "insulation", "wet", "wind", "shell", "blanket", "afterdrop",
                "frostbite", "core",
            ),
            text=(
                "Mild hypothermia brings shivering, clumsiness and poor judgement; severe "
                "hypothermia brings shivering that stops, confusion and collapse — treat the "
                "shivering that stops as the emergency. Move the patient out of wind and off "
                "the ground, remove wet layers, insulate with dry layers and a vapour barrier, "
                "and give warm sweet drinks only if fully alert. Do not rub limbs, give "
                "alcohol, or apply direct heat to extremities; handle the patient gently, "
                "because rough movement can trigger a lethal arrhythmia in severe cases."
            ),
        ),
        Skill(
            id="fractures",
            name="Splinting fractures",
            description=(
                "Immobilising the joints above and below, checking circulation and sling "
                "techniques."
            ),
            tags=("fracture", "splint", "immobilise"),
            keywords=(
                "fracture", "broken", "bone", "splint", "splinting", "immobilise", "immobilize",
                "joint", "sling", "swelling", "deformity", "pulse", "circulation", "arm",
                "leg", "dislocation",
            ),
            text=(
                "Splint in the position found, immobilising the joint above and the joint below "
                "the injury, then recheck distal pulse, sensation and colour before and after. "
                "Pad bony points and rigid material well, and keep the splint snug but not "
                "restricting. Never attempt to straighten a deformed fracture or reduce a "
                "dislocation in the field. Use a sling and body bandage for arm injuries and "
                "traction or a vacuum splint for legs."
            ),
        ),
        Skill(
            id="evacuation",
            name="Evacuation decisions",
            description=(
                "Primary survey, when to call for help, and litter versus self-evacuation."
            ),
            tags=("evacuation", "triage", "rescue"),
            keywords=(
                "evacuate", "evacuation", "rescue", "call", "help", "emergency", "survey",
                "abcde", "airway", "breathing", "circulation", "litter", "carry", "helicopter",
                "signal", "urgent",
            ),
            text=(
                "Run a primary survey first: catastrophic bleeding, airway, breathing, "
                "circulation, disability and exposure. Call for help early and give the "
                "location, number of casualties, injuries and any access constraints. Evacuate "
                "urgently for airway compromise, chest injury, severe bleeding, altered "
                "consciousness or worsening abdominal pain; otherwise stabilise, keep warm and "
                "evacuate by the safest method. A litter needs four to six carriers on rough "
                "ground, so a self-evacuation that can be walked is almost always faster."
            ),
        ),
    ),
)
