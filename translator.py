"""
translator.py — Traduction des segments via GPT-4o.
Envoie tous les segments en un seul appel API, retourne
la liste traduite avec les timestamps d'origine conservés.
"""
import json

from openai import OpenAI

from config import OPENAI_API_KEY
from transcriber import Segment

SYSTEM_PROMPT = (
    "Tu es un traducteur spécialisé dans le contenu pour jeunes adultes hispaniques "
    "(18-30 ans). Traduis en espagnol latino naturel et décontracté, pas de traduction "
    "littérale, utilise les expressions courantes des jeunes latinos. Respecte les temps "
    "verbaux de l'original. "
    "Chaque segment a une durée en secondes. La traduction doit être concise pour tenir "
    "dans cette durée. Privilégie des phrases courtes si la durée est courte. "
    "Retourne uniquement la traduction, rien d'autre."
)

USER_PROMPT_TEMPLATE = """\
Voici une liste de segments à traduire, au format JSON.
Chaque objet contient : start (début), end (fin), duration (durée en secondes), text (texte original).
Retourne UNIQUEMENT un tableau JSON avec les traductions dans le même ordre.
Ne modifie pas le nombre d'éléments. Ne renvoie rien d'autre que le JSON.

Segments :
{segments_json}
"""


class TranslationError(Exception):
    pass


def translate(segments: list[Segment]) -> list[Segment]:
    """
    Traduit une liste de segments en espagnol latino via GPT-4o.
    Un seul appel API pour tous les segments.

    Args:
        segments: Liste de Segment(start, end, text) à traduire.

    Returns:
        Nouvelle liste de Segment avec les textes traduits
        et les timestamps d'origine conservés.

    Raises:
        TranslationError: si la traduction ou le parsing échoue.
    """
    if not segments:
        return []

    payload = [
        {
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "duration": round(seg.end - seg.start, 2),
            "text": seg.text,
        }
        for seg in segments
    ]
    segments_json = json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                    segments_json=segments_json
                )},
            ],
            temperature=0.3,
        )
    except Exception as e:
        raise TranslationError(f"Erreur GPT-4o : {e}") from e

    raw = response.choices[0].message.content.strip()

    # Extraire le JSON même si GPT enveloppe dans un bloc ```json ... ```
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        translations: list[str] = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TranslationError(
            f"Réponse GPT-4o non parseable en JSON : {e}\nRéponse brute : {raw}"
        ) from e

    if len(translations) != len(segments):
        raise TranslationError(
            f"Nombre de traductions ({len(translations)}) != "
            f"nombre de segments ({len(segments)})."
        )

    return [
        Segment(start=seg.start, end=seg.end, text=translation.strip())
        for seg, translation in zip(segments, translations)
    ]


if __name__ == "__main__":
    import sys

    # Lecture depuis stdin ou argument : liste de textes séparés par des lignes vides
    # Usage simple : fournir des segments factices pour tester
    if len(sys.argv) < 2:
        print("Usage: python translator.py '<texte1>' ['<texte2>' ...]")
        sys.exit(1)

    test_segments = [
        Segment(start=i * 3.0, end=(i + 1) * 3.0, text=arg)
        for i, arg in enumerate(sys.argv[1:])
    ]

    try:
        translated = translate(test_segments)
        for seg in translated:
            print(f"[{seg.start:.2f}s - {seg.end:.2f}s] {seg.text}")
    except TranslationError as e:
        print(f"Erreur : {e}")
        sys.exit(1)
