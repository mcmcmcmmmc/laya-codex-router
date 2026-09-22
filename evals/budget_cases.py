"""Twelve bounded task generators with executable answer oracles.

Instances are distinct randomized draws from a fixed synthetic task mixture. This is
not a sample of real user traffic or 150 unrelated task families.
"""
from fractions import Fraction as F
from functools import lru_cache
import itertools as it
import random
import re

from quality_compare import game_oracle

FAMILIES = ('arithmetic', 'records', 'overlap', 'trace', 'shortest', 'topology',
            'intervals', 'boolean', 'assignment', 'modular', 'markov', 'game')


def gauss(a):
    a = [list(map(F, row)) for row in a]
    n = len(a)
    for k in range(n):
        pivot = next(i for i in range(k, n) if a[i][k])
        a[k], a[pivot] = a[pivot], a[k]
        div = a[k][k]
        a[k] = [v/div for v in a[k]]
        for i in range(n):
            if i != k:
                mul = a[i][k]
                a[i] = [x-mul*y for x, y in zip(a[i], a[k])]
    return [row[-1] for row in a]


def make(family, rng):
    if family == 'arithmetic':
        a,b,c,d = [rng.randint(2,35) for _ in range(4)]
        value = (a-b)*c+d
        return f'计算({a}−{b})×{c}+{d}，返回{{"value":整数}}。', {'value':value}
    if family == 'records':
        records = [(i+1,rng.choice(['甲','乙']),rng.randint(1,20),rng.choice(['有效','作废'])) for i in range(8)]
        chosen = [r for r in records if r[1]=='甲' and r[3]=='有效']
        task = '记录格式(编号,类别,金额,状态)：'+str(records)+'。仅保留类别甲且有效的记录，求金额总和及全部编号升序。返回{"sum":整数,"ids":[编号]}。'
        return task, {'sum':sum(r[2] for r in chosen),'ids':[r[0] for r in chosen]}
    if family == 'overlap':
        stem=rng.choice(['aba','aab','bab','aaa']);s=(stem*rng.randint(3,5))+rng.choice(['a','ba','bb'])
        pattern=rng.choice([stem,stem+stem[:2]])
        positions=[i for i in range(len(s)) if s.startswith(pattern,i)]
        assert positions == [m.start() for m in re.finditer('(?='+pattern+')',s)]
        return f'字符串{s}中子串{pattern}允许重叠出现。返回次数和全部起始索引（从0开始）升序，格式{{"count":整数,"positions":[索引]}}。', {'count':len(positions),'positions':positions}
    if family == 'trace':
        n=rng.randint(7,12);start=rng.randint(1,9);mod=rng.randint(3,6);inc=rng.randint(2,5)
        x,y=start,0
        for i in range(n):
            old=x
            if (x+i)%mod==0:x+=inc
            else:x=2*x-i
            y+=x-old
        assert y==x-start
        return f'严格按Python顺序执行，最后x,y是多少？\nx={start}; y=0\nfor i in range({n}):\n old=x\n if (x+i)%{mod}==0: x+={inc}\n else: x=2*x-i\n y+=x-old\n返回{{"x":整数,"y":整数}}。',{'x':x,'y':y}
    if family == 'shortest':
        n=6;edges={(i,i+1):rng.randint(1,6) for i in range(n-1)}
        for i in range(n):
            for j in range(n):
                if i!=j and rng.random()<.22:edges[i,j]=rng.randint(1,8)
        paths=[]
        def dfs(v,path,cost):
            if v==5:paths.append((cost,path));return
            for (a,b),w in edges.items():
                if a==v and b not in path:dfs(b,path+[b],cost+w)
        dfs(0,[0],0);best=min(c for c,p in paths);ways=[p for c,p in paths if c==best]
        d=[[0 if i==j else 10**8 for j in range(n)] for i in range(n)]
        for (a,b),w in edges.items():d[a][b]=w
        for k in range(n):
            for i in range(n):
                for z in range(n):d[i][z]=min(d[i][z],d[i][k]+d[k][z])
        assert best==d[0][5]
        return '有向图顶点0至5，边(起点,终点,正权重)：'+str([(a,b,w) for (a,b),w in sorted(edges.items())])+ '。求0到5的最短距离，以及达到该距离的不同顶点路径数量。返回{"distance":整数,"count":整数}。',{'distance':best,'count':len(ways)}
    if family == 'topology':
        n=6;order=rng.sample(range(n),n);edges=[]
        for i in range(n):
            for j in range(i+1,n):
                if rng.random()<.3:edges.append((order[i],order[j]))
        orders=[p for p in it.permutations(range(n)) if all(p.index(a)<p.index(b) for a,b in edges)]
        dp={0:1}
        for mask in range(1<<n):
            for v in range(n):
                if mask>>v&1 or any(not(mask>>a&1) for a,b in edges if b==v):continue
                nxt=mask|1<<v;dp[nxt]=dp.get(nxt,0)+dp.get(mask,0)
        assert dp[(1<<n)-1]==len(orders)
        return '有向无环图顶点0至5，边'+str(edges)+'。求全部拓扑序数量和字典序最小拓扑序。返回{"count":整数,"first":[顶点编号]}。',{'count':len(orders),'first':list(min(orders))}
    if family == 'intervals':
        jobs=[]
        for i in range(7):
            start=rng.randint(0,10);jobs.append((i,start,start+rng.randint(1,5),rng.randint(1,9)))
        feasible=[]
        for mask in range(128):
            chosen=[j for j in jobs if mask>>j[0]&1];ordered=sorted(chosen,key=lambda j:j[1])
            if all(a[2]<=b[1] for a,b in zip(ordered,ordered[1:])):feasible.append((sum(j[3] for j in chosen),[j[0] for j in chosen]))
        best=max(v for v,ids in feasible);opts=[ids for v,ids in feasible if v==best]
        ordered=sorted(jobs,key=lambda j:j[2]);dp=[0]
        for k,j in enumerate(ordered):
            previous=max([i+1 for i in range(k) if ordered[i][2]<=j[1]] or [0])
            dp.append(max(dp[-1],dp[previous]+j[3]))
        assert dp[-1]==best
        return '任务(编号,开始,结束,收益)：'+str(jobs)+'。选择互不重叠的一组使收益最大，允许前一任务结束时立刻开始下一任务。多个最优组取编号升序列表中字典序最小者。返回{"value":整数,"ids":[编号]}。',{'value':best,'ids':min(opts)}
    if family == 'boolean':
        n=7;clauses=[]
        for _ in range(11):clauses.append(tuple((1 if rng.random()<.5 else -1)*v for v in rng.sample(range(1,n+1),3)))
        def valid(bits):return all(any(bits[abs(v)-1]==int(v>0) for v in c) for c in clauses)
        sols=[p for p in it.product([0,1],repeat=n) if valid(p)]
        def count(v,cs):
            if any(not c for c in cs):return 0
            if not cs:return 2**(n-v+1)
            if v>n:return 1
            total=0
            for bit in (False,True):
                literal=v if bit else -v
                total+=count(v+1,[tuple(x for x in c if x!=-literal) for c in cs if literal not in c])
            return total
        assert count(1,clauses)==len(sols)
        return '布尔变量x1至x7。CNF各子句为'+str(clauses)+'；正整数i代表xi，负整数−i代表非xi，每个子句内部或、子句之间且。求满足赋值总数及按x1至x7拼接的最小01串；无解则first为null。返回{"count":整数,"first":"01串或null"}（无解用JSON null）。',{'count':len(sols),'first':''.join(map(str,min(sols))) if sols else None}
    if family == 'assignment':
        n=rng.choice([5,6]);cost=[[rng.randint(1,19) for _ in range(n)] for _ in range(n)]
        options=[(sum(cost[i][p[i]] for i in range(n)),p) for p in it.permutations(range(n))]
        best,p=min(options)
        @lru_cache(None)
        def solve(mask):
            i=mask.bit_count()
            return 0 if i==n else min(cost[i][j]+solve(mask|1<<j) for j in range(n) if not mask>>j&1)
        assert solve(0)==best
        return f'{n}个员工和{n}个任务均从0编号。成本矩阵（行员工、列任务）'+str(cost)+'。每个员工分配一个任务且任务不重复，使总成本最小；并列按员工顺序的任务编号列表取字典序最小。返回{"cost":整数,"assignment":[任务编号]}。',{'cost':best,'assignment':list(p)}
    if family == 'modular':
        total=rng.randint(15,27);mod=rng.choice([5,7,9]);target=rng.randrange(mod);weight=rng.randint(2,5)
        sols=[(a,b,c) for a,b,c in it.product(range(16),repeat=3) if a+2*b+c==total and (a*c+weight*b)%mod==target and a<c]
        other=[]
        for a in range(16):
            for c in range(a+1,16):
                rem=total-a-c
                if rem>=0 and rem%2==0 and rem//2<=15 and (a*c+weight*(rem//2))%mod==target:other.append((a,rem//2,c))
        assert sols==sorted(other)
        return f'整数a,b,c均在0至15内，满足a+2b+c={total}、a<c、(a×c+{weight}b)除以{mod}余{target}。求全部三元组数量及按(a,b,c)的字典序最小解；无解first=null。返回{{"count":整数,"first":[a,b,c]}}。',{'count':len(sols),'first':list(min(sols)) if sols else None}
    if family == 'markov':
        n=3;weights=[]
        for _ in range(n):weights.append([rng.randint(0,3) for _ in range(n)]+[rng.randint(1,3),rng.randint(1,3)])
        probs=[[F(v,sum(row)) for v in row] for row in weights]
        matrix=[[F(i==k)-probs[i][k] for k in range(n)] for i in range(n)]
        p=gauss([row+[probs[i][n]] for i,row in enumerate(matrix)]);e=gauss([row+[F(1)] for row in matrix])
        mass=[1.,0.,0.];win=steps=0.
        for _ in range(400):
            steps+=sum(mass);win+=sum(mass[i]*float(probs[i][n]) for i in range(n))
            mass=[sum(mass[i]*float(probs[i][k]) for i in range(n)) for k in range(n)]
        assert abs(win-float(p[0]))<1e-9 and abs(steps-float(e[0]))<1e-8
        return '马尔可夫链非吸收态A,B,C和吸收态W,L。从A出发。A,B,C每行依次给出转移到[A,B,C,W,L]的权重，概率为权重除以该行权重之和：'+str(weights)+'。求最终进入W的概率及首次进入W或L所需转移次数的期望，用最简分数字符串（整数可写"2"）。返回{"p":"分数","expected":"分数"}。',{'p':str(p[0]),'expected':str(e[0])}
    if family == 'game':
        start=tuple(rng.randint(3,6) for _ in range(3))
        while start==(6,4,3):start=tuple(rng.randint(3,6) for _ in range(3))
        return '两人轮流取石子，三堆（堆号1,2,3）初始数量'+str(start)+'。每次选一堆取1或2颗，不能选对手上一步选的堆，首步无限制。取走全局最后一颗者立即输；无合法动作也输。双方最优，列出先手所有必胜首步，按堆号、数量升序，无则空数组。返回{"winning_moves":[[堆号,数量],...]}。',game_oracle(start)
    raise ValueError(family)


def generate(n=150, seed=927310):
    rng=random.Random(seed);cases=[];seen=set()
    while len(cases)<n:
        family=rng.choice(FAMILIES);task,answer=make(family,rng)
        if task in seen:continue
        seen.add(task)
        cases.append({'id':f'q{len(cases)+1:03}', 'family':family, 'task':task, 'answer':answer})
    return cases
