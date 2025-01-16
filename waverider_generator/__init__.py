from waverider_generator.generator import waverider as wr

M_inf=5
beta=19.75
height=3.6
width=4.5
dp=[0,0.25,0.15,0.9]

vehicle = wr(M_inf=M_inf,beta=beta,height=height,width=width,dp=dp,n_upper_surface=10000,n_shockwave=10000)


import matplotlib.pyplot as plt
from waverider_generator.plotting_tools import Plot_Base_Plane, Plot_Leading_Edge

base_plane=Plot_Base_Plane(waverider=vehicle,latex=False)
leading_edge=Plot_Leading_Edge(waverider=vehicle,latex=False)
plt.show()


from waverider_generator.cad_export import to_CAD

vehicle_cad=to_CAD(waverider=vehicle,sides='both',export=True,filename='waverider.step',scale=1000)