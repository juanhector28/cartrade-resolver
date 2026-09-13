from app.carly_next.contracts import Candidate
from app.carly_next.parser import build_state
from app.carly_next.ranking import rank_candidates

def test_same_input_same_ranking():
    state = build_state(({"role":"user","content":"Busco Mazda SUV para mis hijos, 550 al mes"},), {"country":"GT"})
    cars = [Candidate("a","Mazda","CX-30",2024,22000,490,18000,"suv",quality_score=.9), Candidate("b","Mazda","CX-5",2024,24000,520,15000,"suv",quality_score=.9)]
    first = [(item.candidate.id, item.score) for item in rank_candidates(cars,state)]
    second = [(item.candidate.id, item.score) for item in rank_candidates(cars,state)]
    assert first == second
