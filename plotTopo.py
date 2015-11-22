import matplotlib
import matplotlib.pyplot as plt
import cPickle as pickle
from mpl_toolkits.basemap import Basemap
import numpy as np

def plotTopo(fig):
    print 'Loading map'
    map = pickle.load(open('map.pickle','rb'))
    # load the bathymetry
    print 'Loading bathy'
    fine=pickle.load(open('fineInt.pickle','rb'))
    clims = [0,800]
    
    map.drawcoastlines(linewidth=0.1)
    X,Y = np.meshgrid(fine['lon'][:-1],fine['lat'][:-1])
    im=map.pcolormesh(X,Y,fine['dep'],rasterized=True,latlon=True,
                      zorder=1,cmap='ocean_r')
    plt.clim(clims)
    map.contour(X,Y,fine['dep'],levels=[50,100,200,300],colors='0.',
                zorder=2,latlon=True)
    parallels = np.arange(0,100,30./60.)
    # labels = [left,right,top,bottom]
    map.drawparallels(parallels,labels=[False,True,True,False])
    meridians = np.arange(10.,351.,30./60.)
    map.drawmeridians(meridians,labels=[True,False,False,True])
    map.fillcontinents(color='wheat',zorder=5) #np.array([255,200,80])/255)
    #x,y = map(-130.5,52.5)
    #x2,y2 = map(-129,53.5)
    #ax.set_xlim(x,x2)
    #ax.set_ylim(y,y2)
    map.drawparallels(parallels,labels=[False,True,True,False])
    map.drawmeridians(meridians,labels=[True,False,False,True])
    # add moorings
    dtype={'names': ('name', 'lat', 'lon'),'formats': ('S12', 'f4', 'f4')}
    moor = np.loadtxt('../Worldclass_MooringsonlyWPsOct21.txt',delimiter=',',dtype=dtype)
    plt.colorbar(im,shrink=0.5)
    for m in  moor:
        map.plot(m[2],m[1],'yd',latlon=True)
    # plot Hauke's Lines
    lines = pickle.load(open('DCLines.pickle','rb'))
    print lines
    for line in lines:
        try:
            map.plot(line['lon'],line['lat'],color='r',alpha=0.7,latlon=True)
        except:
            pass
    #plot stations
    stas=pickle.load(open('Stations.pickle','r'))    
    for nn in range(len(stas['lon'])):
        map.plot(stas['lon'],stas['lat'],'d',color=[0.4,1.,0.4],latlon=True)
    return map
