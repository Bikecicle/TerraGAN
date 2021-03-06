from tensorflow.keras.optimizers import Adam

from model import *
from util import *


LAMBDA = 10


class PGGANTrainer(Session):

    def __init__(self,
                 session_id,
                 latent_size=100,
                 channels=1,
                 n_fmap=None,
                 n_blocks=None,
                 block_types=None,
                 block_batch_sizes=None,
                 block_steps=None,
                 data_path=None):

        super(PGGANTrainer, self).__init__(session_id)

        try:
            self.config['pggan']
        except KeyError:
            sample_latents = []
            for latent in list(random_latents(latent_size, 64)):
                sample_latents.append(list(latent))
            self.config.update({'pggan': True,
                                'block': 0,
                                'steps': 0,
                                'latent_size': latent_size,
                                'channels': channels,
                                'n_fmap': n_fmap,
                                'n_blocks': n_blocks,
                                'block_types': block_types,
                                'block_batch_sizes': block_batch_sizes,
                                'block_steps': block_steps,
                                'data_path': data_path,
                                'sample_latents': sample_latents})

        self.block = self.config['block']
        self.steps = self.config['steps']
        self.n_blocks = self.config['n_blocks']
        self.block_types = self.config['block_types']
        self.block_batch_sizes = self.config['block_batch_sizes']
        self.block_steps = self.config['block_steps']
        if isinstance(self.block_steps, int):
            self.block_steps = [self.block_steps] * self.n_blocks

        self.data_path = self.config['data_path']
        self.sample_latents = np.asarray(self.config['sample_latents'])

        self.pgg = PGGAN(latent_size=self.config['latent_size'],
                         channels=self.config['channels'],
                         n_blocks=self.block + 1,
                         block_types=self.block_types[:self.block + 1],
                         n_fmap=self.config['n_fmap'][:self.block + 1])

        self.gen = self.pgg.build_gen()
        self.dis = self.pgg.build_dis()

        if self.steps > 0:
            print('Loading from save point...')
            version = '{}_{}'.format(self.block, self.steps)
            load_weights(self.gen, 'gen', version, self.session_id)
            load_weights(self.dis, 'dis', version, self.session_id)
        elif self.block > 0:
            print('Loading previous version weights...')
            version = '{}_{}'.format(self.block - 1, self.block_steps[self.block - 1])
            load_weights(self.gen, 'gen', version, self.session_id)
            load_weights(self.dis, 'dis', version, self.session_id)
        else:
            print('Building new model...')

        self.gen_opt = Adam(lr=0.001, beta_1=0, beta_2=0.99, epsilon=10e-8)
        self.dis_opt = Adam(lr=0.001, beta_1=0, beta_2=0.99, epsilon=10e-8)

        images = np.load(root_dir + self.data_path)['x']
        ch0 = images[:, :, :, 0]
        ch1 = images[:, :, :, 1]
        print('Channel 0: [{}, {}]'.format(np.amin(ch0), np.amax(ch0)))
        print('Channel 1: [{}, {}]'.format(np.amin(ch1), np.amax(ch1)))
        self.dataset = tf.image.resize(images, [self.pgg.final_res, self.pgg.final_res]).numpy()

    def get_alpha(self, n_samples, cap=1.0):

        alpha = min(2.0 * self.steps / self.block_steps[self.block], cap)
        alpha_array = np.repeat(alpha, n_samples).reshape(n_samples, 1)

        return alpha_array

    def real_images(self, n_samples):

        idx = np.random.randint(0, self.dataset.shape[0], n_samples)
        images = self.dataset[idx]

        return images

    @tf.function
    def compute_WGAN_GP(self, images, latents, batch_size, alpha):

        epsilon = tf.random.uniform(shape=[batch_size, 1, 1, 1], minval=0, maxval=1)

        with tf.GradientTape(persistent=True) as dis_tape:
            with tf.GradientTape() as gp_tape:
                fake_images = self.gen([latents, alpha], training=True)
                fake_images_mixed = epsilon * images + ((1 - epsilon) * fake_images)
                fake_mixed_pred = self.dis([fake_images_mixed, alpha], training=True)

            # Compute gradient penalty
            grads = gp_tape.gradient(fake_mixed_pred, fake_images_mixed)
            grad_norms = tf.sqrt(tf.reduce_sum(tf.square(grads), axis=[1, 2, 3]))
            gradient_penalty = tf.reduce_mean(tf.square(grad_norms - 1))

            fake_pred = self.dis([fake_images, alpha], training=True)
            real_pred = self.dis([images, alpha], training=True)

            dis_loss = tf.reduce_mean(fake_pred) - tf.reduce_mean(real_pred) + LAMBDA * gradient_penalty

        # Calculate the gradients for discriminator
        dis_gradients = dis_tape.gradient(dis_loss, self.dis.trainable_variables)

        # Apply the gradients to the optimizer
        self.dis_opt.apply_gradients(zip(dis_gradients, self.dis.trainable_variables))

        with tf.GradientTape() as gen_tape:
            fake_images = self.gen([latents, alpha], training=True)
            fake_pred = self.dis([fake_images, alpha], training=True)
            gen_loss = -tf.reduce_mean(fake_pred)

        # Calculate the gradients for discriminator
        gen_gradients = gen_tape.gradient(gen_loss, self.gen.trainable_variables)

        # Apply the gradients to the optimizer
        self.gen_opt.apply_gradients(zip(gen_gradients, self.gen.trainable_variables))

        return dis_loss, gen_loss

    def train_step(self):

        batch_size = self.block_batch_sizes[self.block]

        images = self.real_images(batch_size)
        latents = random_latents(self.pgg.latent_size, batch_size)
        alpha = self.get_alpha(batch_size)

        d_loss, g_loss = self.compute_WGAN_GP(images, latents, batch_size, alpha)

        if self.steps % 100 == 0:
            print('\nBlock ' + str(self.block)
                  + ', step ' + str(self.steps) + ':')
            print('Alpha:', alpha[0, 0])
            print('D:', d_loss.numpy())
            print('G:', g_loss.numpy())

        if self.steps % 10000 == 0:
            self.save()

        if self.steps % 1000 == 0:
            self.evaluate(self.gen)

        self.steps += 1

    def train_block(self):

        print('Starting block ' + str(self.block) + ' at step ' + str(self.steps))

        while self.steps <= self.block_steps[self.block]:
            self.train_step()

        if self.block < self.n_blocks - 1:
            # Next block
            self.block += 1
            self.steps = 0
            self.save()
            print('Block training complete. Restart to begin next block')
        else:
            # Model complete
            print('Final block training complete')

    def save(self):

        version = '{}_{}'.format(self.block, self.steps)
        save_weights(self.gen, 'gen', version, self.session_id)
        save_weights(self.dis, 'dis', version, self.session_id)

        self.config['block'] = self.block
        self.config['steps'] = self.steps
        self.config.save()

        print('--Weights saved')

    def evaluate(self, model):

        imgs = model.predict([self.sample_latents, self.get_alpha(64)])

        r = []
        for i in range(0, 64, 8):
            r.append(np.concatenate(imgs[i:i + 8], axis=1))
        grid = np.concatenate(r, axis=0)

        norm = (grid[:, :, 0:1] + 1) / 2
        diff = grid[:, :, 1:2]
        real = norm + diff

        save_image(np.clip(norm, 0.0, 1.0), 'norm', self.block, self.steps, self.session_id)
        save_image(np.clip(real, 0.0, 1.0), 'real', self.block, self.steps, self.session_id)
        print('--Images saved')
