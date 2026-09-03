"""
skills/loader.py — LangChain Progressive Disclosure On-Demand Skill Loader

Implements the official LangChain Skills pattern:
https://docs.langchain.com/oss/python/langchain/multi-agent/skills-sql-assistant

1. Discovers all skills in skills/*/SKILL.md.
2. Exposes lightweight descriptions for the agent's system prompt.
3. Provides @tool load_skill(skill_name) to progressively load full instructions,
   business logic, and playbooks on demand.
"""

import json
import logging
from pathlib import Path
from typing import TypedDict
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent


class Skill(TypedDict):
    name: str
    description: str
    content: str
    path: str


def _parse_skill_md(file_path: Path) -> Skill:
    """Parses a SKILL.md file with optional YAML frontmatter."""
    raw_text = file_path.read_text(encoding="utf-8")
    name = file_path.parent.name
    description = f"Specialized skill for {name}"
    content = raw_text

    if raw_text.startswith("---"):
        parts = raw_text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            content = parts[2].strip()
            lines = frontmatter.strip().splitlines()
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("name:"):
                    name = line.split("name:", 1)[1].strip()
                    i += 1
                elif line.startswith("description:"):
                    desc_parts = [line.split("description:", 1)[1].replace(">-", "").strip()]
                    i += 1
                    while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                        desc_parts.append(lines[i].strip())
                        i += 1
                    description = " ".join(p for p in desc_parts if p)
                else:
                    i += 1


    return {
        "name": name,
        "description": description,
        "content": content,
        "path": str(file_path),
    }


def load_all_skills() -> dict[str, Skill]:
    """Discovers and caches all SKILL.md definitions in the skills/ directory."""
    skills_map = {}
    for skill_file in SKILLS_DIR.glob("*/SKILL.md"):
        try:
            skill = _parse_skill_md(skill_file)
            # Register by both folder name and frontmatter name
            skills_map[skill_file.parent.name] = skill
            if skill["name"] != skill_file.parent.name:
                skills_map[skill["name"]] = skill
        except Exception as exc:
            logger.error("Failed to parse skill %s: %s", skill_file, exc)
    return skills_map


# Cache of loaded skills
_SKILLS_CACHE = load_all_skills()


def get_available_skills_prompt() -> str:
    """Builds a concise list of skill descriptions to inject into the Agent's system prompt."""
    unique_skills = {}
    for k, v in _SKILLS_CACHE.items():
        unique_skills[v["name"]] = v["description"]

    lines = ["## Available On-Demand Skills:"]
    for name, desc in unique_skills.items():
        lines.append(f"- **{name}**: {desc}")
    lines.append(
        "\nUse the `load_skill` tool when you need detailed domain instructions, "
        "rules, or customer playbooks to handle your task."
    )
    return "\n".join(lines)


@tool
def load_skill(skill_name: str) -> str:
    """Load the full instructions, business rules, and playbooks of a skill on-demand.

    Use this when you need comprehensive guidelines to execute a specific task
    (e.g., cross-selling, profiling, intent parsing).

    Args:
        skill_name: The name of the skill to load (e.g., 'cross_sell_agent', 'profiler', 'parser', 'timing')
    """
    skill = _SKILLS_CACHE.get(skill_name)
    if not skill:
        # Try normalizing hyphens/underscores
        norm = skill_name.replace("-", "_")
        skill = _SKILLS_CACHE.get(norm)
    if not skill:
        norm = skill_name.replace("_", "-")
        skill = _SKILLS_CACHE.get(norm)

    if not skill:
        available = ", ".join(sorted(set(s["name"] for s in _SKILLS_CACHE.values())))
        return f"Skill '{skill_name}' not found. Available skills: {available}"

    # Check if there are playbooks or lookup assets associated with this skill
    assets_dir = Path(skill["path"]).parent / "assets"
    extra_context = []

    playbooks_dir = assets_dir / "playbooks"
    if playbooks_dir.exists():
        playbook_files = list(playbooks_dir.glob("*.json"))
        extra_context.append(f"\n### Associated Playbooks Available ({len(playbook_files)}):")
        for pb in playbook_files:
            try:
                data = json.loads(pb.read_text(encoding="utf-8"))
                extra_context.append(f"- **{pb.stem}**: {data.get('playbook_name', pb.name)} — {data.get('description', '')}")
            except Exception:
                pass

    result = f"# Loaded Skill: {skill['name']}\n\n{skill['content']}"
    if extra_context:
        result += "\n" + "\n".join(extra_context)
    return result


def load_playbook(segment: str) -> dict:
    """Helper to load a customer segment playbook JSON directly."""
    pb_file = SKILLS_DIR / "cross_sell_agent" / "assets" / "playbooks" / f"{segment}.json"
    if pb_file.exists():
        try:
            return json.loads(pb_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load playbook %s: %s", segment, exc)
    return {}
