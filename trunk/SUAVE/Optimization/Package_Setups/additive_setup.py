## @ingroup Optimization-Package_Setups
# additive_setup.py
#
# Created:  Apr 2017, T. MacDonald
# Modified: Jun 2017, T. MacDonald

# ----------------------------------------------------------------------
#  Imports
# ----------------------------------------------------------------------

import autograd.numpy as np
import SUAVE
try:
    import pyOpt
except:
    pass
import sklearn
from sklearn import gaussian_process
from SUAVE.Optimization import helper_functions as help_fun
from SUAVE.Methods.Utilities.latin_hypercube_sampling import latin_hypercube_sampling
from scipy.stats import norm
import os
import sys

# ----------------------------------------------------------------------
#  Additive Solve Functions
# ----------------------------------------------------------------------

## @ingroup Optimization-Package_Setups
def Additive_Solve(problem,num_fidelity_levels=2,num_samples=10,max_iterations=10,
                   tolerance=1e-6,opt_type='basic',num_starts=3,print_output=True):
    """Solves a multifidelity problem using an additive corrections

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    problem             [nexus()]
    num_fidelity_levels [int]
    num_samples         [int]
    max_iterations      [int]
    tolerance           [float]
    opt_type            [str]
    num_starts          [int]
    print_output        [bool]
    
    Outputs:
    (fOpt,xOpt)  [tuple]

    Properties Used:
    N/A
    """        
    
    if print_output == False:
        devnull = open(os.devnull,'w')
        sys.stdout = devnull    
    
    if num_fidelity_levels != 2:
        raise NotImplementedError
    
    # History writing
    f_out = open('add_hist.txt','w')
    import datetime
    f_out.write(str(datetime.datetime.now())+'\n')
    
    inp = problem.optimization_problem.inputs
    obj = problem.optimization_problem.objective
    con = problem.optimization_problem.constraints 

    # Set inputs
    nam = inp[:,0] # Names
    ini = inp[:,1] # Initials
    bnd = inp[:,2] # Bounds
    scl = inp[:,3] # Scale
    typ = inp[:,4] # Type

    (x,scaled_constraints,x_low_bound,x_up_bound,con_up_edge,con_low_edge) = scale_vals(inp, con, ini, bnd, scl)  
    
    # Get initial set of samples
    x_samples = latin_hypercube_sampling(len(x),num_samples,bounds=(x_low_bound,x_up_bound),criterion='center')
    
    # Initialize objective and constraint variables
    f = np.zeros([num_fidelity_levels,num_samples])
    g = np.zeros([num_fidelity_levels,num_samples,len(scaled_constraints)])
    
    for level in range(1,num_fidelity_levels+1):
        problem.fidelity_level = level
        for ii,x in enumerate(x_samples):
            res = evaluate_model(problem,x,scaled_constraints)
            f[level-1,ii]    = res[0]  # objective value
            g[level-1,ii,:]  = res[1]  # constraints vector
    
    converged = False
    
    for kk in range(max_iterations):
        # Build objective surrogate
        f_diff = f[1,:] - f[0,:]
        f_additive_surrogate_base = gaussian_process.GaussianProcessRegressor()
        f_additive_surrogate = f_additive_surrogate_base.fit(x_samples, f_diff)     
        
        # Build constraint surrogate
        g_diff = g[1,:] - g[0,:]
        g_additive_surrogate_base = gaussian_process.GaussianProcessRegressor()
        g_additive_surrogate = g_additive_surrogate_base.fit(x_samples, g_diff)     
        
        # Optimize corrected model
        
        # Chose method ---------------
        if opt_type == 'basic': # Next point determined by surrogate optimum
            opt_prob = pyOpt.Optimization('SUAVE',evaluate_corrected_model, \
                                      obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)       
        
            x_eval = latin_hypercube_sampling(len(x),1,bounds=(x_low_bound,x_up_bound),criterion='random')[0]
            
            # Set up opt_prob
            initialize_opt_vals(opt_prob,obj,inp,x_low_bound,x_up_bound,con_low_edge,con_up_edge,nam,con,x_eval)  
               
            opt = pyOpt.pySNOPT.SNOPT()      
            
            problem.fidelity_level = 1
            outputs = opt(opt_prob, sens_type='FD',problem=problem, \
                          obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)#, sens_step = sense_step)  
            fOpt = outputs[0][0]
            xOpt = outputs[1]

        elif opt_type == 'MEI': # Next point determined by maximum expected improvement
            fstar = np.min(f[1,:])
            opt_prob = pyOpt.Optimization('SUAVE',evaluate_expected_improvement, \
                                      obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate,fstar=fstar)     
            
            # Set up opt_prob
            initialize_opt_vals(opt_prob,obj,inp,x_low_bound,x_up_bound,con_low_edge,con_up_edge,nam,con,None)     
               
            # Use a global optimizer
            opt = pyOpt.pyALPSO.ALPSO()    
            opt.setOption('maxOuterIter',value=20)
            opt.setOption('seed',value=1.)
            
            problem.fidelity_level = 1
            
            outputs = opt(opt_prob,problem=problem, \
                          obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate,fstar=fstar,cons=con)#, sens_step = sense_step)
            fOpt  = np.nan 
            imOpt = outputs[0]
            xOpt  = outputs[1]
        
        # ---------------------------------
        
        # Add new samples and check objective and constraint values
        f = np.hstack((f,np.zeros((num_fidelity_levels,1))))
        g = np.hstack((g,np.zeros((num_fidelity_levels,1,len(con)))))
        x_samples = np.vstack((x_samples,xOpt))
        for level in range(1,num_fidelity_levels+1):
            problem.fidelity_level = level
            res = evaluate_model(problem,xOpt,scaled_constraints)
            f[level-1][-1] = res[0]
            g[level-1][-1] = res[1]
            
        # History writing
        f_out.write('Iteration: ' + str(kk+1)    + '\n')
        f_out.write('x0       : ' + str(xOpt[0]) + '\n')
        f_out.write('x1       : ' + str(xOpt[1]) + '\n')
        if opt_type == 'basic':
            f_out.write('expd hi  : ' + str(fOpt) + '\n')
        elif opt_type == 'MEI':
            f_out.write('expd imp : ' + str(imOpt) + '\n')
        f_out.write('low obj : ' + str(f[0][-1]) + '\n')
        f_out.write('hi  obj : ' + str(f[1][-1]) + '\n') 
        if kk == (max_iterations-1): # Reached maximum number of iterations
            f_diff = f[1,:] - f[0,:]
            if opt_type == 'basic': # If basic setting f already has the expected optimum
                fOpt = f[1][-1]
            elif opt_type == 'MEI': # If MEI, find the optimum of the final surrogate
                opt_prob = pyOpt.Optimization('SUAVE',evaluate_corrected_model, \
                                              obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)       
            
                min_ind = np.argmin(f[1])
                x_eval = x_samples[min_ind]
            
                # Set up opt_prob
                initialize_opt_vals(opt_prob,obj,inp,x_low_bound,x_up_bound,con_low_edge,con_up_edge,nam,con,x_eval)    
            
                fOpt, xOpt = run_objective_optimization(opt_prob,problem,f_additive_surrogate,g_additive_surrogate)
        
                f_out.write('x0_opt  : ' + str(xOpt[0]) + '\n')
                f_out.write('x1_opt  : ' + str(xOpt[1]) + '\n')                
                f_out.write('final opt : ' + str(fOpt) + '\n')
                
            print 'Iteration Limit Reached'
            break        
            
        
        if np.abs(fOpt-f[1][-1]) < tolerance: # Converged within a tolerance
            print 'Convergence reached'      
            f_out.write('Convergence reached')
            f_diff = f[1,:] - f[0,:]
            converged = True
            if opt_type == 'MEI':
                opt_prob = pyOpt.Optimization('SUAVE',evaluate_corrected_model, \
                                              obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)       
            
                min_ind = np.argmin(f[1])
                x_eval = x_samples[min_ind]
            
                initalize_opt_vals(opt_prob,obj,inp,x_low_bound,x_up_bound,con_low_edge,con_up_edge,nam,con,x_eval)    
            
                opt = pyOpt.pySNOPT.SNOPT()      
            
                problem.fidelity_level = 1
                outputs = opt(opt_prob, sens_type='FD',problem=problem, \
                              obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)#, sens_step = sense_step)  
                fOpt = outputs[0][0]
                xOpt = outputs[1]
                f_out.write('x0_opt  : ' + str(xOpt[0]) + '\n')
                f_out.write('x1_opt  : ' + str(xOpt[1]) + '\n')                
                f_out.write('final opt : ' + str(fOpt) + '\n')            
            break        
        
        fOpt = f[1][-1]*1.
    
    if converged == False:
        print 'Iteration Limit reached'
        f_out.write('Maximum iteration limit reached')
    
    # Save sample data
    np.save('x_samples.npy',x_samples)
    np.save('f_data.npy',f)
    f_out.close()
    print fOpt,xOpt
    if print_output == False:
        sys.stdout = sys.__stdout__     
    return (fOpt,xOpt)
    
## @ingroup Optimization-Package_Setups    
def evaluate_model(problem,x,cons):
    """Solves the optimization problem to get the objective and constraints

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    problem   [nexus()]
    x         [array]
    cons      [array]
    
    Outputs:
    f         [float]
    g         [array]

    Properties Used:
    N/A    
    """
    f  = np.array(0.)
    g  = np.zeros(np.shape(cons))
    
    f  = problem.objective(x)
    g  = problem.all_constraints(x)
    
    return f,g

## @ingroup Optimization-Package_Setups    
def evaluate_corrected_model(x,problem=None,obj_surrogate=None,cons_surrogate=None):
    """Evaluates the corrected model with the low fidelity plus the corrections

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    x              [array]
    problem        [nexus()]
    obj_surrogate  [fun()]
    cons_surrogate [fun()]
    
    Outputs:
    obj            [float]
    const          [array]
    fail           [bool]

    Properties Used:
    N/A    
    
    """
    
    obj   = problem.objective(x)
    const = problem.all_constraints(x).tolist()
    fail  = np.array(np.isnan(obj.tolist()) or np.isnan(np.array(const).any())).astype(int)
    
    obj_addition  = obj_surrogate.predict(x)
    cons_addition = cons_surrogate.predict(x)
    
    obj   = obj + obj_addition
    const = const + cons_addition
    const = const.tolist()[0]

    print 'Inputs'
    print x
    print 'Obj'
    print obj
    print 'Con'
    print const
        
    return obj,const,fail

## @ingroup Optimization-Package_Setups
def evaluate_expected_improvement(x,problem=None,obj_surrogate=None,cons_surrogate=None,fstar=np.inf,cons=None):
    """Evaluates the expected improvement of the point x

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    x              [array]
    problem        [nexus()]
    obj_surrogate  [fun()]
    cons_surrogate [fun()]
    fstar          [float]
    cons           [vector]
    
    Outputs:
    -EI            [float]
    const          [array]
    fail           [bool]

    Properties Used:
    N/A    
    
    """    

    obj   = problem.objective(x)
    const = problem.all_constraints(x).tolist()
    fail  = np.array(np.isnan(obj.tolist()) or np.isnan(np.array(const).any())).astype(int)
    
    # Get uncertainty information
    obj_addition, obj_sigma   = obj_surrogate.predict(x,return_std=True)
    cons_addition, cons_sigma = cons_surrogate.predict(x,return_std=True)
    
    fhat  = obj[0] + obj_addition
    # Calculate expected improvement (based on Schonlau, Computer Experiments and Global Optimization, 1997)
    EI    = (fstar-fhat)*norm.cdf((fstar-fhat)/obj_sigma) + obj_sigma*norm.pdf((fstar-fhat)/obj_sigma)
    const = const + cons_addition
    
    # Adjust signs for optimizer (this is specific to ALPSO)
    signs  = np.ones([1,len(cons)])
    offset = np.zeros([1,len(cons)])
    for ii,con in enumerate(cons):
        if cons[ii][1] == '>':
            signs[0,ii] = -1
        offset[0,ii] = cons[ii][2]
    
    
    const = const*signs - offset*signs
    const = const.tolist()[0]

    print 'Inputs'
    print x
    print 'Obj'
    print -EI
    print 'Con'
    print const
        
    return -EI,const,fail

## @ingroup Optimization-Package_Setups
def expected_improvement_carpet(lbs,ubs,problem,obj_surrogate,cons_surrogate,fstar,show_log_improvement=False):
    """Makes a carpet plot of the expected improvement

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    lbs                  [array]
    lbs                  [array]
    problem              [nexus()]
    obj_surrogate        [fun()]
    cons_surrogate       [fun()]
    fstar                [float]
    show_log_improvement [bool]
    
    Outputs:
    Alluring plots that you could only dream of

    Properties Used:
    N/A    
    
    """       

    # Assumes 2D
    # To use before global opt:
    # expected_improvement_carpet(x_low_bound, x_up_bound, problem, f_additive_surrogate, g_additive_surrogate, fstar)  

    problem.fidelity_level = 1
    linspace_num = 40
    
    x0s = np.linspace(lbs[0],ubs[0],linspace_num)
    x1s = np.linspace(lbs[1],ubs[1],linspace_num) 
        
    EI = np.zeros([linspace_num,linspace_num])        
        
    for ii,x0 in enumerate(x0s):
        for jj,x1 in enumerate(x1s):
            x = [x0,x1]
            obj   = problem.objective(x)
            const = problem.all_constraints(x).tolist()    
        
            obj_addition, obj_sigma   = obj_surrogate.predict(x,return_std=True)
            cons_addition, cons_sigma = cons_surrogate.predict(x,return_std=True)
            
            fhat      = obj[0] + obj_addition
            EI[jj,ii] = (fstar-fhat)*norm.cdf((fstar-fhat)/obj_sigma) + obj_sigma*norm.pdf((fstar-fhat)/obj_sigma)
            const     = const + cons_addition
            const     = const.tolist()[0]
            
            print ii
            print jj
            print 'Expected Improvement: ' + str(EI[ii,jj])
            
    import matplotlib.pyplot as plt
            
    num_levels = 20
            
    plt.figure(1)
    levals = np.linspace(np.min(EI),np.max(EI),num_levels)
    CS = plt.contourf(x0s, x1s, EI, 20, linewidths=2,levels=levals)
    cbar = plt.colorbar(CS)
    cbar.ax.set_ylabel('Expected Improvement')
    
    if show_log_improvement == True: # Display log expected information as well
        EI = np.log(EI)
        print np.min(EI[EI!=-np.inf])
        if np.min(EI[EI!=-np.inf]) > -100:
            levals = np.linspace(np.min(EI[EI!=-np.inf]),np.max(EI),num_levels)
        else:
            levals = np.linspace(-40,np.max(EI),num_levels)    
        plt.figure(2)
        CS = plt.contourf(x0s, x1s, EI, 20, linewidths=2,levels=levals)
        cbar = plt.colorbar(CS)
        cbar.ax.set_ylabel('Log Expected Improvement')    
    
    plt.show()
    
## @ingroup Optimization-Package_Setups    
def scale_vals(inp,con,ini,bnd,scl):
    """Scales values to help setup the problem

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    inp                         [array]
    con                         [array]
    ini                         [array]
    bnd                         [array]
    scl                         [array]
    
    Outputs:
        tuple:
            x                   [array]
            scaled_constraints  [array]
            x_low_bounds        [array]
            x_up_bounds         [array]
            con_up_edge         [array]
            con_low_edge        [array]

    Properties Used:
    N/A    
    
    """     

    # Pull out the constraints and scale them
    bnd_constraints = help_fun.scale_const_bnds(con)
    scaled_constraints = help_fun.scale_const_values(con,bnd_constraints)

    x            = ini/scl        
    x_low_bound  = []
    x_up_bound   = []
    edge         = []
    con_up_edge  = []
    con_low_edge = []

    for ii in xrange(0,len(inp)):
        x_low_bound.append(bnd[ii][0]/scl[ii])
        x_up_bound.append(bnd[ii][1]/scl[ii])

    for ii in xrange(0,len(con)):
        edge.append(scaled_constraints[ii])
        if con[ii][1]=='<':
            con_up_edge.append(edge[ii])
            con_low_edge.append(-np.inf)
        elif con[ii][1]=='>':
            con_up_edge.append(np.inf)
            con_low_edge.append(edge[ii])
        elif con[ii][1]=='=':
            con_up_edge.append(edge[ii])
            con_low_edge.append(edge[ii])

    x_low_bound  = np.array(x_low_bound)
    x_up_bound   = np.array(x_up_bound)
    con_up_edge  = np.array(con_up_edge)         
    con_low_edge = np.array(con_low_edge)        

    return (x,scaled_constraints,x_low_bound,x_up_bound,con_up_edge,con_low_edge)    

## @ingroup Optimization-Package_Setups
def initialize_opt_vals(opt_prob,obj,inp,x_low_bound,x_up_bound,con_low_edge,con_up_edge,nam,con,x_eval):
    """Sets up the optimization values 

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    opt_prob         [pyopt_problem()]
    obj              [float]
    inp              [array]
    x_low_bound      [array]
    x_up_bound       [array]
    con_low_edge     [array]
    con_up_edge      [array]
    nam              [list of str]
    con              [array]
    x_eval           [array]
    
    Outputs:
    N/A
    
    Properties Used:
    N/A    
    
    """        
    
    for ii in xrange(len(obj)):
        opt_prob.addObj('f',100) 
    for ii in xrange(0,len(inp)):
        vartype = 'c'
        if x_eval == None:
            opt_prob.addVar(nam[ii],vartype,lower=x_low_bound[ii],upper=x_up_bound[ii]) 
        else:
            opt_prob.addVar(nam[ii],vartype,lower=x_low_bound[ii],upper=x_up_bound[ii],value=x_eval[ii])    
    for ii in xrange(0,len(con)):
        if con[ii][1]=='<':
            opt_prob.addCon(nam[ii], type='i', upper=con_up_edge[ii])
        elif con[ii][1]=='>':
            opt_prob.addCon(nam[ii], type='i', lower=con_low_edge[ii],upper=np.inf)
        elif con[ii][1]=='=':
            opt_prob.addCon(nam[ii], type='e', equal=con_up_edge[ii])        
            
    return

## @ingroup Optimization-Package_Setups
def run_objective_optimization(opt_prob,problem,f_additive_surrogate,g_additive_surrogate):
    """Runs SNOPT to optimize

    Assumptions:
    N/A

    Source:
    N/A

    Inputs:
    opt_prob             [pyopt_problem()]
    problem              [nexus()]
    f_additive_surrogate [fun()]  
    g_additive_surrogate [fun()]
    
    Outputs:
    fOpt                 [float]
    xOpt                 [array]
    
    Properties Used:
    N/A    
    
    """      
    
    opt = pyOpt.pySNOPT.SNOPT()

    problem.fidelity_level = 1
    outputs = opt(opt_prob, sens_type='FD',problem=problem, \
                  obj_surrogate=f_additive_surrogate,cons_surrogate=g_additive_surrogate)#, sens_step = sense_step)  
    fOpt = outputs[0][0]
    xOpt = outputs[1]
    
    return fOpt, xOpt