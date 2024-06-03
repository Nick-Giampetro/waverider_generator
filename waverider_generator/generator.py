import numpy as np
from scipy.interpolate import interp1d
import bezier.curve as bcurve
from scipy.optimize import root_scalar
from  scipy.integrate import solve_ivp
from scipy.interpolate import UnivariateSpline
'''
+---------------------------+
| Created by Jade Nassif    |
|                           |
| jade.nassif2002@gmail.com |
+---------------------------+
'''

'''
The purpose of this code is to generate waverider geometries based on the osculating
cone inverse design method. The user inputs the following:
- Freestream Mach number 'M_inf'
- Shock angle 'beta'
- Height of the waverider at the base plane 'height"
- Width of the waverider at the base plane 'width"
- Design parameters 'X1', 'X2', 'X3', 'X4'
- Number of osculating planes 'n_planes'
- Number of points in the streamwise direction 'n_streamwise'

The parametrisation is based on the work by Son et. al [1]

[1] Jiwon Son, Chankyu Son, and Kwanjung Yee. 
'A Novel Direct Optimization Framework for Hypersonic Waverider Inverse Design Methods'.
In: Aerospace 9.7 (June 2022), p. 348. issn: 2226-4310. doi: 10.3390/aerospace9070348.

The output is a CAD geometry of the waverider defined by surfaces.

The code structure is based on the class "waverider" 

Note that the following convention is used in this code:
x --> streamwise direction
y --> transverse direction
z --> spanwise direction
with origin at the waverider tip

A local 2D coordinate system with origin at the shockwave symmetry plane also exists with 
y_bar=y-height, z_bar=z and x=length 
'''

class waverider():
    
    # constructor
    # expected input for dp (design parameters) is a list [X1,X2,X3,X4]
    # STATUS OF FUNCTION : STABLE
    def __init__(self,M_inf,beta,height,width,dp,n_upper_surface,n_shockwave,**kwargs):

        #initialise class attributes below
        self.M_inf=M_inf
        self.beta=beta
        self.height=height
        self.width=width
        
        #ratio of specific heats
        self.gamma=1.4

        #computes self.theta
        self.Compute_Deflection_Angle()

        self.X1=dp[0]
        self.X2=dp[1]
        self.X3=dp[2]
        self.X4=dp[3]

        # check that condition for inverse design is respected
        if not ((self.X2/((1-self.X1)**4))<(7/64)*(self.width/self.height)**4):
            raise ValueError("Condition for inverse design not respected, check design parameters X1 and X2")
    
        # check optional input "n_planes"
        if "n_planes" in kwargs:
            n_planes = kwargs["n_planes"]
            if not (isinstance(n_planes, int) and n_planes >= 10):
                raise TypeError("The number of planes must be an integer and at least 10")
            self.n_planes = n_planes

        # check optional input "n_streamwise"
        if "n_streamwise" in kwargs:
            n_streamwise = kwargs["n_streamwise"]
            if not (isinstance(n_streamwise, int) and n_streamwise >= 10):
                raise TypeError("The number of streamwise points must be an integer and at least 10")
            self.n_streamwise = n_streamwise

        # obtain length of waverider from tip to base plane
        self.length=height/np.tan(self.beta*np.pi/180)

        ''''define the shockwave based on the control points 
        -----------------------------------------------------'''
        self.s_cp=np.zeros((5,2))

        # all five points are evenly distributed in z
        self.s_cp[:,0]=np.transpose(np.linspace(self.X1*self.width,self.width,5))

        # assign the y_bar of the last point
        self.s_cp[-1,1]=self.X2*self.height

        # express the control points as individual points
        # column 1 is z and column 2 is y_bar
        self.s_P0=self.s_cp[0,:]
        self.s_P1=self.s_cp[1,:]
        self.s_P2=self.s_cp[2,:]
        self.s_P3=self.s_cp[3,:]
        self.s_P4=self.s_cp[4,:]

        ''' define the upper surface curve
        ---------------------------------------------------'''
        self.us_cp=np.zeros((4,2))

        # assign z coordinates of all points defining upper surface, equally spaced
        self.us_cp[:,0]=np.transpose(np.linspace(0,self.width,4))

        #assign y_bar coordinates of all points on upper surface
        self.us_cp[0,1]=self.height
        self.us_cp[1,1]=self.height-(1-self.X2)*self.X3
        self.us_cp[2,1]=self.height-(1-self.X2)*self.X4

        #assign last point using the P4 computed for the shockwave
        self.us_cp[3,:]=self.s_P4

        #define control points individually
        self.us_P0=self.us_cp[0,:]
        self.us_P1=self.us_cp[1,:]
        self.us_P2=self.us_cp[2,:]
        self.us_P3=self.us_cp[3,:]

        # create an interpolation object for upper surface
        # self.Interpolate_Upper_Surface
        self.Create_Interpolated_Upper_Surface(n=n_upper_surface)

        # next step is to calculate intersections with upper surface
        # start by defining the sample of points for the shockwave in local coordinates z and y
        self.z_local_shockwave=np.linspace(0,self.width,self.n_planes+2)
        self.z_local_shockwave=self.z_local_shockwave[1:-1]
        
        #calculate the corresponding y_bar coordinates by first creating a interp1d object for the 
        # non-flat part of the curve
        self.Create_Interpolated_Shockwave(n=n_shockwave)

        #obtain the y_bar values for the z sample in self.y_bar_shockwave
        self.Get_Shockwave_Curve()

        #obtain the intersection with the upper surface in self.us_waverider.local_intersections_us
        self.Find_Intersections_With_Upper_Surface()

        # next step is to obtain the LE points in the global coordinate system
        # initialise LE object
        self.leading_edge=np.zeros((self.n_planes+2,3))

        # tip is already at 0,0,0
        # set the last point
        self.leading_edge[-1,:]=np.array([self.length,self.Local_to_Global(self.X2*self.height),self.width])

        # initialise an object for the cone centers
        self.cone_centers=np.zeros((self.n_planes,3))
        # osculate through the planes
        self.Compute_Leading_Edge_And_Cone_Centers()

        # next step is to compute the upper surface
        self.upper_surface_x=np.zeros((self.n_planes+1,self.n_streamwise))
        self.upper_surface_y=np.zeros((self.n_planes+1,self.n_streamwise))
        self.upper_surface_z=np.zeros((self.n_planes+1,self.n_streamwise))
        # add the symmetry plane
        self.upper_surface_x[0,:]=np.linspace(0,self.length,self.n_streamwise)
        self.upper_surface_y[0,:]=0
        self.upper_surface_z[0,:]=0

        #create an alternative way of storing the upper surface streams
        

        # compute the upper surface in self.leading edge
        self.Compute_Upper_Surface()

        # next step is to trace the streamlines, start by computing the flow deflection in flat regions
        # self.theta
        self.Compute_Deflection_Angle()
        self.streams=[]
        
        self.Streamline_Tracing()
        
    def Streamline_Tracing(self):

        for i,le_point in enumerate(self.leading_edge):
            if le_point[0]<=self.X1*self.width or self.X2==0:
                bottom_surface_y=le_point[1]-np.tan(self.theta*np.pi/180)*(self.length-le_point[0])
                x=np.linspace(le_point[0],self.length,self.n_streamwise)[:,None]
                y=np.linspace(le_point[1],bottom_surface_y,self.n_streamwise)[:,None]
                z=np.full((y.shape),le_point[2])

                self.streams.append(np.column_stack([x,y,z]))


    def Compute_Upper_Surface(self):
        
        for i in range(0,self.n_planes):
            self.upper_surface_x[i+1,:]=np.linspace(self.leading_edge[i,0],self.length,self.n_streamwise)
            self.upper_surface_y[i+1,:]=np.linspace(self.leading_edge[i,1],self.Local_to_Global(self.local_intersections_us[i,1]),self.n_streamwise)
            self.upper_surface_z[i+1,:]=np.linspace(self.leading_edge[i,2],self.local_intersections_us[i,0],self.n_streamwise)
        
    def Compute_Leading_Edge_And_Cone_Centers(self):

        for i,z in enumerate(self.z_local_shockwave):
             
            if z<=self.X1*self.width or self.X2==0:
                self.cone_centers[i,0]=self.length-((self.local_intersections_us[i,1]-self.y_bar_shockwave[i,0])/np.tan(self.beta*np.pi/180))
                self.cone_centers[i,1]=self.Local_to_Global(self.local_intersections_us[i,1])
                self.cone_centers[i,2]=float(z)

                self.leading_edge[i+1,:]=self.cone_centers[i,:]

            else:
                #calculate corresponding t value
                t=self.Find_t_Value(z)
                # first derivative and radius
                first_derivative,_,_=self.First_Derivative(t)
                radius=self.Calculate_Radius_Curvature(t)

                self.leading_edge[i+1,:]=self.cone_centers[i,:]
                # get angle theta
                theta=np.arctan(first_derivative)
                
                # get x value for cone center
                self.cone_centers[i,0]=float(self.length-radius/np.tan(self.beta*np.pi/180))

                # get y value for cone center
                self.cone_centers[i,1]=float(self.Local_to_Global(self.y_bar_shockwave[i,0])+np.cos(theta)*radius) 

                # get z value for cone center
                self.cone_centers[i,2]=float(z-radius*np.sin(theta))

                # get the location of the intersection
                self.leading_edge[i+1,:]=self.Intersection_With_Freestream_Plane(self.cone_centers[i,0],
                                                                                self.cone_centers[i,1],
                                                                                self.cone_centers[i,2],
                                                                                self.length,
                                                                                self.Local_to_Global(self.y_bar_shockwave[i,0]),
                                                                                z,
                                                                                self.Local_to_Global(self.local_intersections_us[i,1]))
                


    def Intersection_With_Freestream_Plane(self,x_C,y_C,z_C,x_S,y_S,z_S,y_target):

        #  ALL COORDINATES IN GLOBAL SYSTEM
        # x_C,y_C,z_C are coordinates of cone center
        # x_S,y_S,z_S are coordinates of shock location in osculating plane

        # need to find where y=y_target
        # parametric curve defined with vectors CM and CS
        k=(y_target-y_S)/(y_C-y_S)

        x_I=x_S+k*(x_C-x_S)
        y_I=y_target
        z_I=z_S+k*(z_C-z_S)
        return np.array([x_I,y_I,z_I])


        
    def Calculate_Radius_Curvature(self,t):
        
        _,dzdt,dydt=self.First_Derivative(float(t))
        dzdt2,dydt2=self.Second_derivative(float(t))

        radius= 1/(abs((dzdt*dydt2-dydt*dzdt2))/((dzdt**2+dydt**2)**(3/2)))
        return radius

        
    def Find_t_Value(self,z):

        def f(t):
            return self.Bezier_Shockwave(t)[0]-z
        
        intersection=root_scalar(f,bracket=[0,1])
        return intersection.root

    def Find_Intersections_With_Upper_Surface(self):

        self.local_intersections_us=np.zeros((self.n_planes,2))

        for i,z in enumerate(self.z_local_shockwave):

            if z<=self.X1*self.width or self.X2==0:
                self.local_intersections_us[i,0]=z
                self.local_intersections_us[i,1]=self.Interpolate_Upper_Surface(z)
            else:
                first_derivative,_,_=self.Get_First_Derivative(z)
                # print(first_derivative)
                intersection=self.Intersection_With_Upper_Surface(first_derivative=first_derivative,z_s=float(z),y_s=float(self.y_bar_shockwave[i,:]))
                self.local_intersections_us[i,:]=intersection

    def Intersection_With_Upper_Surface(self,first_derivative,z_s,y_s):

        # get the constant c and slope for the line between the two points
        c=y_s+(1/first_derivative)*z_s
        m= -1/first_derivative

        # define the function used to find the intersection between the two curves
        def f(z):
            return Equation_of_Line(z,m,c) - self.Interpolate_Upper_Surface(z)
        
        # use a computational method to get the root
        intersection = root_scalar(f, bracket=[0, self.width])

        # extract local coordinates of the root
        z=intersection.root
        y=Equation_of_Line(z,m,c)
        return np.array([z,y])

    def Get_First_Derivative(self,z):

        t=self.Find_t_Value(z)

        first_derivative,dzdt,dydt=self.First_Derivative(t)

        return first_derivative,dzdt,dydt


    def Get_Shockwave_Curve(self):

        self.y_bar_shockwave=np.zeros((self.n_planes,1))

        for i,z in enumerate(self.z_local_shockwave):
            if z<=self.width*self.X1:
                self.y_bar_shockwave[i,0]=0
            else:
                self.y_bar_shockwave[i,0]=float(self.Interpolate_Shockwave(float(z)))

    def Create_Interpolated_Shockwave(self,n):
        
        t_values=np.linspace(0,1,n)
        points=np.zeros((n,2))

        for i,t in enumerate(t_values):
            points[i,:]=self.Bezier_Shockwave(t)

        
        self.Interpolate_Shockwave=interp1d(points[:,0],points[:,1],kind='linear')


    def Create_Interpolated_Upper_Surface(self,n):

        # values of t for the bezier curve
        t_values=np.linspace(0,1,n)

        points=np.zeros((n,2))

        # get points along the bezier curve representing the upper surface
        for i, t in enumerate(t_values):
            points[i, :] = self.Bezier_Upper_Surface(t)

        # store interp1d objected as an attribute
        self.Interpolate_Upper_Surface=interp1d(points[:,0],points[:,1],kind='linear')
    
    def Compute_Deflection_Angle(self):

        tanTheta=2*cot(self.beta*np.pi/180)*(self.M_inf**2*np.sin(self.beta*np.pi/180)**2-1)/(self.M_inf**2*(self.gamma+np.cos(2*self.beta*np.pi/180))+2)

        self.theta=np.arctan(tanTheta)*180/np.pi

    # def Calculate_First_Derivatives(self):

        # calculate slope for all 







    """
    AUXILIARY FUNCTIONS    
    """    

    def Bezier_Shockwave(self,t):

        point=(1-t)**4*self.s_P0+4*(1-t)**3*t*self.s_P1+6*(1-t)**2*t**2*self.s_P2+4*(1-t)*t**3*self.s_P3+t**4*self.s_P4

        return point
    
    # returns slope m, dz/dt and dy/dt
    def First_Derivative(self, t):

        first_derivative = 4 * (1-t)**3 * (self.s_P1 - self.s_P0) + 12 * (1-t)**2 * t * (self.s_P2 - self.s_P1) + 12 * (1-t) * t**2 * (self.s_P3 - self.s_P2) + 4 * t**3 * (self.s_P4 - self.s_P3)
    
        return first_derivative[1]/first_derivative[0],first_derivative[0],first_derivative[1]
    
    # returns components of second derivative, z and y respectively
    def Second_derivative(self, t):

        second_derivative = 12 * (1-t)**2 * (self.s_P2 - 2 * self.s_P1 + self.s_P0) + 24 * (1-t) * t * (self.s_P3 - 2 * self.s_P2 + self.s_P1) + 12 * t**2 * (self.s_P4 - 2 * self.s_P3 + self.s_P2)
        return second_derivative[0],second_derivative[1]
    
    def Bezier_Upper_Surface(self, t):

        point = (1 - t)**3 * self.us_P0 + 3 * (1 - t)**2 * t * self.us_P1 + 3 * (1 - t) * t**2 * self.us_P2 + t**3 * self.us_P3

        return point

    def Local_to_Global(self,y):
    # convert local coordinates to global coordinates
        y=y-self.height

        return y
        

# Auxiliary Functions
def Euclidean_Distance(x1,y1,x2,y2):
    return np.sqrt((x2-x1)**2+(y2-y1)**2)

def Equation_of_Line(z,m,c):
    return m*z+c


def cot(angle):
    return 1/np.tan(angle)

def cone_field(Mach, theta, beta, gamma):
    d = np.arctan(2.0 / np.tan(beta) * (pow(Mach, 2) * pow(np.sin(beta),
                                                           2) - 1.0) / (pow(Mach, 2) * (gamma + np.cos(2 * beta)) + 2.0))
    Ma2 = 1.0 / np.sin(beta - d) * np.sqrt((1.0 + (gamma - 1.0) / 2.0 * pow(Mach, 2) * pow(
        np.sin(beta), 2)) / (gamma * pow(Mach, 2) * pow(np.sin(beta), 2) - (gamma - 1.0) / 2.0))
    V = 1.0 / np.sqrt(2.0 / ((gamma - 1.0) * pow(Ma2, 2)) + 1.0)
    Vr = V * np.cos(beta - d)
    Vt = -(V * np.sin(beta - d))

    xt = np.array([Vr, Vt])
    
    sol = solve_ivp(TM, (beta, theta), xt, args=(gamma,))
    Vrf = UnivariateSpline(sol.t[::-1], sol.y[0, ::-1], k=min(3, sol.t.size-1))
    Vtf = UnivariateSpline(sol.t[::-1], sol.y[1, ::-1], k=min(3, sol.t.size-1))
    return [Vrf, Vtf]