import matplotlib.pyplot as plt

from model import *
from util import *
from latent_manipulation import *


class TileGenerator(Session):

    def __init__(self, session_id, segment_idx, overlap=2, steps=None):

        # Load session config
        super(TileGenerator, self).__init__(session_id)

        # Set parameters
        self.segment_idx = segment_idx
        self.overlap = overlap

        # Build progressively-grown gan and get segmented generator
        self.pgg = PGGAN(latent_size=self.config['latent_size'],
                         channels=self.config['channels'],
                         n_blocks=self.config['n_blocks'],
                         block_types=self.config['block_types'],
                         n_fmap=self.config['n_fmap'])

        self.gen_a, self.gen_b = self.pgg.build_gen_stable(segment_idx)

        if steps is None:
            self.steps = self.config['steps']
        else:
            self.steps = steps

        # Load weights into generators
        version = '{}_{}'.format(self.pgg.n_blocks - 1, self.steps)
        load_weights(self.gen_a, 'gen', version, self.session_id)
        load_weights(self.gen_b, 'gen', version, self.session_id)

        # Get some variables from the generators for later use
        self.res_a = self.gen_a.outputs[0].shape[1]
        self.res_b = self.gen_b.outputs[0].shape[1]
        self.scale_b = self.res_b / self.res_a
        self.latent_tile_map = {}

        # Initialize weight mask for gen_a (used to blend intermediate latent tiles)
        self.weight_mask_a = np.zeros(shape=(self.res_a, self.res_a, 1))
        r = (self.res_a - 1.0) / 2.0
        max_weight = np.linalg.norm(np.asarray([r, r]))
        for i in range(self.res_a):
            x = i - r
            for j in range(self.res_a):
                y = j - r
                weight = np.linalg.norm(np.asarray([x, y]))
                self.weight_mask_a[i, j, 0] = max_weight - weight + 1

        # Initialize weight mask for gen_b (used to blend final tile outputs)
        self.weight_mask_b = np.zeros(shape=(self.res_b, self.res_b, 1))
        r = (self.res_b - 1.0) / 2.0
        max_weight = np.linalg.norm(np.asarray([r, r]))
        for i in range(self.res_b):
            x = i - r
            for j in range(self.res_b):
                y = j - r
                weight = np.linalg.norm(np.asarray([x, y]))
                self.weight_mask_b[i, j, 0] = (max_weight - weight) ** 4 + 1

        # Create latent manipulator
        self.lm = LatentManipulator(session_id, 'msm10')

    def generate_tile(self, latents, tile_ids, rotations, name, save_img=True):

        chunk_size_a = self.res_a * 3 - self.overlap * 2

        chunk_a = np.zeros(shape=(chunk_size_a, chunk_size_a, self.gen_a.outputs[0].shape[-1]))
        weight_map_a = np.zeros(shape=(chunk_size_a, chunk_size_a, 1))

        tiles = []

        # Lookup intermediate tiles and generate if missing
        for i in range(9):
            tile_id = str(tile_ids[i])
            if tile_id != '-1':
                try:
                    tile = self.latent_tile_map[tile_id]
                except KeyError:
                    latents[i] = self.lm.center_latent(latents[i], 'mean_5')
                    latents[i] = self.lm.move_latent(latents[i], 'mean_5', -1.0)
                    tile = self.gen_a.predict(np.asarray([latents[i]]))[0]
                    self.latent_tile_map[tile_id] = tile
                tiles.append(np.rot90(tile, rotations[i], axes=(0, 1)))
            else:
                tiles.append(None)

        # Blend intermediate latent tiles together
        for i in range(3):
            y = (self.res_a - self.overlap) * (2 - i)
            for j in range(3):
                x = (self.res_a - self.overlap) * j
                if tiles[i * 3 + j] is not None:
                    chunk_a[y:y + self.res_a, x:x + self.res_a] += tiles[i * 3 + j] * self.weight_mask_a
                    weight_map_a[y:y + self.res_a, x:x + self.res_a] += self.weight_mask_a

        chunk_a /= weight_map_a + 1e-8

        chunk_size_b = int(chunk_size_a * self.scale_b)

        chunk_b = np.zeros(shape=(chunk_size_b, chunk_size_b, self.gen_b.outputs[0].shape[-1]))
        weight_map_b = np.zeros(shape=(chunk_size_b, chunk_size_b, 1))

        # Blend tile outputs together
        for i in range(3):
            ya = (self.res_a - self.overlap) * (2 - i)
            yb = int(ya * self.scale_b)
            for j in range(3):
                xa = (self.res_a - self.overlap) * j
                xb = int(xa * self.scale_b)

                tile_b = self.gen_b.predict(np.asarray([np.rot90(chunk_a[ya:ya + self.res_a, xa:xa + self.res_a], -rotations[i * 3 + j], (0, 1))]))[0]
                tile_b = np.rot90(tile_b, rotations[i * 3 + j], (0, 1))
                tile_b = (tile_b + 1.0) / 2.0

                chunk_b[yb:yb + self.res_b, xb:xb + self.res_b] += tile_b * self.weight_mask_b
                weight_map_b[yb:yb + self.res_b, xb:xb + self.res_b] += self.weight_mask_b

        chunk_b /= weight_map_b + 1e-8

        # Slice out the center tile and trim some of the blended overlap to avoid redundancy
        tile_start = int((self.res_a - self.overlap / 2) * self.scale_b)
        out_res = int((self.res_a - self.overlap) * self.scale_b)
        tile_out = chunk_b[tile_start:tile_start + out_res, tile_start:tile_start + out_res]

        # Save an image of the output for debugging
        if save_img:
            save_image(tile_out[:, :, 1], name, 6, 1, 'ue4_comms')

        return tile_out


# Some stuff left over from debugging
if __name__ == '__main__':
    latents_top = random_latents(128, 9)
    tile_ids_top = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    rotations_top = [0, 0, 1, 0, 0, 1, 0, 0, 1]
    latents_right = random_latents(128, 9)
    tile_ids_right = [9, 10, 11, 2, 5, 8, 1, 4, 7]
    rotations_right = [0, 0, 0, 0, 0, 0, 3, 3, 3]
    tg = TileGenerator('pgf6', 2, 4)

    tile_top = tg.generate_tile(latents_top, tile_ids_top, rotations_top, 'a')
    plt.imshow(tile_top[:, :, 1])
    plt.show()

    tile_right = tg.generate_tile(latents_right, tile_ids_right, rotations_right, 'b')
    plt.imshow(tile_right[:, :, 1])
    plt.show()

    tile_a = np.zeros(shape=[tile_top.shape[0] * 2, tile_top.shape[1], tile_top.shape[2]])
    tile_a[:tile_top.shape[0]] = np.rot90(tile_top, 3, axes=(0, 1))
    tile_a[tile_top.shape[0]:] = tile_right
    plt.imshow(tile_a[:, :, 1])
    plt.show()
