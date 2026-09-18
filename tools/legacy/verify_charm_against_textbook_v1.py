"""Verify compute_net_charm's math against the textbook Black-Scholes charm (Haug)."""
import math
def phi(x): return math.exp(-0.5*x*x)/math.sqrt(2*math.pi)
def N(x):   return 0.5*(1+math.erf(x/math.sqrt(2)))

def textbook_charm_call(S,K,T,sig,r=0.0,q=0.0):
    """Haug: dDelta/dT for a call (q=0). charm_dt (calendar time) = -this."""
    d1=(math.log(S/K)+(r-q+0.5*sig*sig)*T)/(sig*math.sqrt(T))
    d2=d1-sig*math.sqrt(T)
    return -phi(d1)*((2*(r-q)*T - d2*sig*math.sqrt(T))/(2*T*sig*math.sqrt(T))) + q*math.exp(-q*T)*N(d1)

def ours(S,K,T,sig):
    d1=(math.log(S/K)+0.5*sig*sig*T)/(sig*math.sqrt(T))
    d2=d1-sig*math.sqrt(T)
    return -phi(d1)*d2/(2.0*T)

print(f"{'S':>7}{'K':>7}{'T(yr)':>9}{'sigma':>7}{'r':>6}{'textbook dD/dT':>17}{'ours':>13}{'ratio':>9}")
print("-"*76)
for (S,K,T,sig,r) in [(743.29,745,1/365,0.15,0.05),(743.29,745,1/365,0.15,0.0),
                      (743.29,740,7/365,0.18,0.05),(743.29,760,30/365,0.20,0.05),
                      (100,100,0.25,0.20,0.05),(100,100,0.25,0.20,0.0)]:
    tb=textbook_charm_call(S,K,T,sig,r); o=ours(S,K,T,sig)
    # our value is meant to be dDelta/dt (calendar) = -dDelta/dT
    print(f"{S:>7.2f}{K:>7.1f}{T:>9.5f}{sig:>7.2f}{r:>6.2f}{tb:>17.4f}{o:>13.4f}{(o/-tb if tb else float('nan')):>9.3f}")

print("\n-> ratio 1.000 would mean ours == -(textbook). Deviation = the dropped r/(sigma*sqrt(T)) term.")
print("   Note r=0.00 rows: with no rate the two MUST agree exactly if the algebra is right.\n")

# Does the docstring formula match the code?
def docstring_formula(S,K,T,sig,r):
    d1=(math.log(S/K)+(r+0.5*sig*sig)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    return -phi(d1)*( d2/(2*S*sig*math.sqrt(T)) + r/(sig*math.sqrt(T)) )   # as written at line 660
S,K,T,sig,r=743.29,745,1/365,0.15,0.05
print(f"docstring(line 660) = {docstring_formula(S,K,T,sig,r):.6f}")
print(f"code   (line 788)   = {ours(S,K,T,sig):.6f}")
print("-> if these differ, the documented formula is not the implemented one.")
