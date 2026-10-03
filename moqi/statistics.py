"""Small deterministic numerical routines; no model downloads or GPU required."""
import math


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values)-1)*q
    lo = int(pos)
    return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(pos-lo)


def beta_tail(alpha, beta, threshold):
    """Regularized incomplete beta via modified Lentz continued fraction."""
    if alpha <= 0 or beta <= 0 or not 0 <= threshold <= 1:
        raise ValueError('Invalid Beta parameters')
    if threshold == 0:
        return 1.0
    if threshold == 1:
        return 0.0
    def fraction(a,b,x):
        tiny = 1e-300
        c = 1.0
        d = 1-(a+b)*x/(a+1)
        d = 1/max(abs(d),tiny)*(1 if d >= 0 else -1)
        h = d
        for m in range(1,401):
            aa = m*(b-m)*x/((a+2*m-1)*(a+2*m))
            d = 1+aa*d
            c = 1+aa/c
            if abs(d) < tiny: d = tiny
            if abs(c) < tiny: c = tiny
            d = 1/d
            h *= d*c
            aa = -(a+m)*(a+b+m)*x/((a+2*m)*(a+2*m+1))
            d = 1+aa*d
            c = 1+aa/c
            if abs(d) < tiny: d = tiny
            if abs(c) < tiny: c = tiny
            d = 1/d
            delta = d*c
            h *= delta
            if abs(delta-1) < 3e-13:
                return h
        raise ArithmeticError('Beta posterior did not converge')
    x = threshold
    weight = math.exp(math.lgamma(alpha+beta)-math.lgamma(alpha)-math.lgamma(beta)+
                      alpha*math.log(x)+beta*math.log1p(-x))
    if x < (alpha+1)/(alpha+beta+2):
        return max(0.0,min(1.0,1-weight*fraction(alpha,beta,x)/alpha))
    return max(0.0,min(1.0,weight*fraction(beta,alpha,1-x)/beta))


def fit_thermal(rows):
    # rows: (Tout-T, signed HVAC input u, dT/dt in degrees/hour).
    if len(rows) < 12:
        return dict(status='insufficient_data',samples=len(rows))
    xx = sum(x*x for x,u,y in rows)
    uu = sum(u*u for x,u,y in rows)
    xu = sum(x*u for x,u,y in rows)
    xy = sum(x*y for x,u,y in rows)
    uy = sum(u*y for x,u,y in rows)
    determinant = xx*uu-xu*xu
    if determinant <= max(1e-12,xx*uu*1e-10):
        return dict(status='unidentifiable',samples=len(rows))
    a = (xy*uu-uy*xu)/determinant
    k = (uy*xx-xy*xu)/determinant
    if a <= 0 or k <= 0 or not math.isfinite(a+k) or not .05 <= 1/a <= 240:
        return dict(status='nonphysical_fit',samples=len(rows))
    mse = sum((y-a*x-k*u)**2 for x,u,y in rows)/len(rows)
    return dict(status='fitted',samples=len(rows),tau_hours=1/a,k_deg_per_hour=k,mse=mse)


def heating_duration(model, indoor, outdoor, target):
    if model.get('status') != 'fitted' or target <= indoor:
        return 0.0 if target <= indoor else None
    tau,k = model['tau_hours'],model['k_deg_per_hour']
    equilibrium = outdoor+tau*k
    if equilibrium <= target:
        return None
    ratio = (target-equilibrium)/(indoor-equilibrium)
    return -tau*math.log(ratio)*60 if 0 < ratio <= 1 else None


def optimal_absence(durations, regret_cost, waste_per_minute):
    if not durations or regret_cost <= 0 or waste_per_minute <= 0:
        return None
    choices = sorted({0, *durations})
    def cost(timeout):
        return sum(regret_cost*(d <= timeout+10 and d > timeout)+
                   waste_per_minute*min(d,timeout) for d in durations)/len(durations)
    best = min(choices,key=cost)
    return dict(timeout_minutes=best,cost=cost(best),samples=len(durations),
                regret_cost=regret_cost,waste_per_minute=waste_per_minute)
