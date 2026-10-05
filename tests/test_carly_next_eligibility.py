from app.carly_next.contracts import Candidate
from app.carly_next.eligibility import filter_eligible
from app.carly_next.parser import build_state

def test_monthly_cap_is_a_hard_filter():
    state = build_state(({"role":"user","content":"Busco Mazda SUV, 550 al mes"},), {"country":"GT"})
    cars = [
        Candidate("ok","Mazda","CX-30",2024,20000,540,20000,"suv"),
        Candidate("over","Mazda","CX-5",2024,25000,590,15000,"suv"),
    ]
    assert [car.id for car in filter_eligible(cars,state)] == ["ok"]
