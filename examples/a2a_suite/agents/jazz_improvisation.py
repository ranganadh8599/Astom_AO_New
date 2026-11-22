"""Jazz improvisation agent: harmony, chord scales and vocabulary."""

from __future__ import annotations

from a2a_suite.spec import AgentSpec, Skill

SPEC = AgentSpec.from_catalog(
    "jazz-improvisation",
    skills=(
        Skill(
            id="harmony",
            name="Harmony and guide tones",
            description=(
                "ii-V-I progressions, guide tones, extensions and rhythm changes."
            ),
            tags=("ii-v-i", "guide-tones", "harmony"),
            keywords=(
                "harmony", "harmonic", "ii-v-i", "ii", "v-i", "251", "guide", "tone",
                "tones", "changes", "rhythm", "extension", "tritone", "substitution",
                "turnaround", "blues",
            ),
            text=(
                "A ii-V-I in major is iim7 - V7 - Imaj7, and its guide tones are the thirds "
                "and sevenths that move by step or hold: in C, F-A (Fmaj7) to F-Ab (G7) to "
                "E-G... the seventh of ii falls to the third of V, then the seventh of V falls "
                "to the third of I. Outline those two lines first, then add extensions (9, 11, "
                "13) sparingly. Rhythm changes are 32 bars of I-vi-ii-V | iii-VI-ii-V over the "
                "first half, then a bridge of dominant cycles."
            ),
        ),
        Skill(
            id="scales",
            name="Chord-scale choices",
            description=(
                "Dorian, mixolydian, altered, bebop dominant and blues scale, and when each "
                "fits."
            ),
            tags=("dorian", "mixolydian", "altered"),
            keywords=(
                "scale", "scales", "dorian", "mixolydian", "altered", "lydian", "locrian",
                "bebop", "blues", "pentatonic", "whole", "tone", "diminished", "mode",
                "chord-scale",
            ),
            text=(
                "Minor sevenths take dorian; dominant sevenths take mixolydian, or altered "
                "(7#9, b13) when resolving to a minor chord. Maj7 chords take ionian, or "
                "lydian when the fourth is exposed. Bebop dominant adds a major seventh to the "
                "mixolydian scale so chord tones land on strong beats. The blues scale works "
                "over all three chords in a blues, and the major pentatonic is the safest "
                "starting point on a new tune."
            ),
        ),
        Skill(
            id="vocabulary",
            name="Building vocabulary",
            description=(
                "Transcription, motivic development, playing behind the beat and practice "
                "loops."
            ),
            tags=("transcription", "motifs", "practice"),
            keywords=(
                "transcribe", "transcription", "lick", "licks", "vocabulary", "motif",
                "motivic", "develop", "phrase", "phrasing", "swing", "timing", "practice",
                "slow", "chorus",
            ),
            text=(
                "Learn solos by ear from recordings: sing the line, find it on the instrument, "
                "then write it out. Take one two-bar idea and develop it by transposing, "
                "inverting, changing rhythm or moving it through the changes. Practise with a "
                "metronome on 2 and 4 at half speed; swing comes from the eighth-note "
                "placement, not from playing fast. Aim for phrases with space, not continuous "
                "eighth notes."
            ),
        ),
    ),
)
