import os
import math
import PIL.Image
import numpy as np
import matplotlib.pyplot as plt

# standard hgt is 1201x1201 where each pixel is 3 arc-seconds (90 m)

dim = 1024
max_elevation = 8000
min_elevation = -100

sample_size = 512
samples_per_img = 32


def process_section(name):
    raw_dir = 'raw_data/vfp/' + name + '/'

    lats = []
    lons = []

    d = int(math.sqrt(os.path.getsize(raw_dir + os.listdir(raw_dir)[0]) / 2))
    for f in os.listdir(raw_dir):
        lats.append(int(f[1:3]))
        lons.append(int(f[4:7]))

    lat0 = min(lats)
    lat1 = max(lats)
    lon0 = min(lons)
    lon1 = max(lons)

    data = np.zeros(((lat1 - lat0 + 1) * d, (lon1 - lon0 + 1) * d))
    print(data.shape)
    for f in os.listdir(raw_dir):
        print(raw_dir + f)
        s = np.fromfile(raw_dir + f, np.dtype('>i2'), d * d).reshape((d, d))
        lat = int(f[1:3])
        lon = int(f[4:7])
        for y in range(len(s)):
            for x in range(len(s[0])):
                data[(lat1 - lat) * d + y][(lon1 - lon) * d + x] = s[y][x]
        # plt.imsave('data/vfp/' + name + '/' + f[:-4] + '.jpg', s, cmap='gray')
        # np.save('data/' + name + '/' + f[:-4] + '.npy', s)
    plt.imsave('data/region/' + name + '.png', data, vmin=-max_elevation, vmax=max_elevation, cmap='gray')

def hgt_to_jpg(file, target):
    d = int(math.sqrt(os.path.getsize(file) / 2))
    hgt = np.fromfile(file, np.dtype('>i2'), d * d).reshape((d, d))
    region = str(os.path.split(file)[0].split('/')[-1])
    for s in range(samples_per_img):
        pos = np.random.randint(0, d - sample_size, 2)
        sample = hgt[pos[0]:pos[0] + sample_size, pos[1]:pos[1] + sample_size]
        sample = np.rot90(sample, k=np.random.randint(0, 4), axes=[0, 1])
        plt.imsave(os.path.join(target, region + '_' + os.path.basename(file))[:-4] + '_' + str(s) + '.jpg', sample,
                   cmap='gray')


def process_all(root, target, depth=0):
    if not os.path.exists(target):
        os.mkdir(target)
    print('  ' * depth + '-Processing ' + root)
    for p in os.listdir(root):
        path = os.path.join(root, p)
        if os.path.isdir(path):
            process_all(path, target, depth + 1)
        elif path[-3:] == 'hgt':
            print('  ' * (depth + 1) + '-Sampling ' + p)
            hgt_to_jpg(path, target)


raw_dir = 'raw_data/vfp/'
img_dir = 'data/vfp_512_2/'
h5_path = '../tileGAN/datasets/vfp.h5'

process_all(raw_dir, img_dir)

'''
n_img = len(os.listdir(img_dir))
imgs = np.asarray([np.asarray(PIL.Image.open(os.path.join(img_dir, f))) for f in os.listdir(img_dir)])
exp = HDF5Exporter(h5_filename=h5_path, resolution=dim, channels=3)
exp.add_images_channel_last(imgs)
exp.close()
'''