import os
from pathlib import Path

files = [
    r'd:\CodeSpaces\cangjie-ai\ark-agentic-space\ark-agentic\src\ark_agentic\studio\services\skill_service.py',
    r'd:\CodeSpaces\cangjie-ai\ark-agentic-space\ark-agentic\src\ark_agentic\studio\services\tool_service.py'
]

for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if 'resolve_agent_dir' not in content:
        content = 'from ark_agentic.core.utils.env import resolve_agent_dir\n' + content
    
    # Replace skills_dir initialization
    old_skills = 'skills_dir = agents_root / agent_id / "skills"'
    new_skills = '''agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    skills_dir = agent_dir / "skills"'''
    content = content.replace(old_skills, new_skills)
    
    # Replace tools_dir initialization
    old_tools = 'tools_dir = agents_root / agent_id / "tools"'
    new_tools = '''agent_dir = resolve_agent_dir(agents_root, agent_id)
    if not agent_dir:
        raise FileNotFoundError(f"Agent not found: {agent_id}")
    tools_dir = agent_dir / "tools"'''
    content = content.replace(old_tools, new_tools)
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)

print("Patch applied to skill_service.py and tool_service.py.")
