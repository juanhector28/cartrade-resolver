class SessionStore:
    def __init__(self):
        self.states = {}

    def get(self, session_id):
        return self.states.get(session_id)

    def put(self, session_id, state):
        self.states[session_id] = state
