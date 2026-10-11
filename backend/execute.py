from tools.register import execute_tool


def execute_command(command):
    return execute_tool(command)


def execute_plan(plan):
    results = []

    if not isinstance(plan, dict):
        return results

    steps = plan.get("steps", [])

    if not isinstance(steps, list):
        return results

    for step in steps:
        if not isinstance(step, dict):
            continue

        result = execute_tool(step)

        results.append({
            "action": step.get("action"),
            "result": result
        })

        if not result.get("success", False):
            break

    return results