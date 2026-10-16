"""Browser interface (TypeScript): a local HTTP server + screen logic without drawing.

Game logic, the coach and the engine stay in Python. The screens in ``screens/`` have no drawing code:
they hold state, react to actions from the browser and every frame hand over a state "snapshot" (JSON) that the TypeScript interface draws as vectors.
"""
