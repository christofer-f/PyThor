mport os
from argparse import ArgumentParser
from collections import OrderedDict

import torch
from pytorch_lightning import Trainer, LightningModule
from torch.nn import functional as F

from pythor.datamodules import MNISTDataLoaders
from pythor.Networks.Linear.GAN.gan_components import Generator, Discriminator


class GAN(LightningModule):

    def __init__(self, hparams=None):
        super().__init__()
        self.__check_hparams(hparams)
        self.hparams = hparams

        self.dataloaders = MNISTDataLoaders(save_path=os.getcwd())

        # networks
        self.generator = self.init_generator(self.img_dim)
        self.discriminator = self.init_discriminator(self.img_dim)

        # cache for generated images
        self.generated_imgs = None
        self.last_imgs = None

    def __check_hparams(self, hparams):
        self.input_channels = hparams.input_channels if hasattr(hparams, 'input_channels') else 1
        self.input_width = hparams.input_width if hasattr(hparams, 'input_width') else 28
        self.input_height = hparams.input_height if hasattr(hparams, 'input_height') else 28
        self.latent_dim = hparams.latent_dim if hasattr(hparams, 'latent_dim') else 32
        self.batch_size = hparams.batch_size if hasattr(hparams, 'batch_size') else 32
        self.b1 = hparams.b1 if hasattr(hparams, 'b1') else 0.5
        self.b2 = hparams.b2 if hasattr(hparams, 'b2') else 0.999
        self.learning_rate = hparams.learning_rate if hasattr(hparams, 'learning_rate') else 0.0002
        self.img_dim = (self.input_channels, self.input_width, self.input_height)

    def init_generator(self, img_dim):
        generator = Generator(latent_dim=self.latent_dim, img_shape=img_dim)
        return generator

    def init_discriminator(self, img_dim):
        discriminator = Discriminator(img_shape=img_dim)
        return discriminator

    def forward(self, z):
        """
        Allows infernce to be about generating images
        x = gan(z)
        :param z:
        :return:
        """
        return self.generator(z)

    def adversarial_loss(self, y_hat, y):
        return F.binary_cross_entropy(y_hat, y)

    def generator_step(self, x):
        # sample noise
        z = torch.randn(x.shape[0], self.latent_dim)
        z = z.type_as(x)

        # generate images
        self.generated_imgs = self(z)

        # ground truth result (ie: all real)
        real = torch.ones(x.size(0), 1)
        real = real.type_as(x)
        g_loss = self.generator_loss(real)

        tqdm_dict = {'g_loss': g_loss}
        output = OrderedDict({
            'loss': g_loss,
            'progress_bar': tqdm_dict,
            'log': tqdm_dict
        })
        return output

    def generator_loss(self, real):
        # adversarial loss is binary cross-entropy
        g_loss = self.adversarial_loss(self.discriminator(self.generated_imgs), real)
        return g_loss

    def discriminator_loss(self, x):
        # how well can it label as real?
        valid = torch.ones(x.size(0), 1)
        valid = valid.type_as(x)

        real_loss = self.adversarial_loss(self.discriminator(x), valid)

        # how well can it label as fake?
        fake = torch.zeros(x.size(0), 1)
        fake = fake.type_as(fake)

        fake_loss = self.adversarial_loss(
            self.discriminator(self.generated_imgs.detach()), fake)

        # discriminator loss is the average of these
        d_loss = (real_loss + fake_loss) / 2
        return d_loss

    def discriminator_step(self, x):
        # Measure discriminator's ability to classify real from generated samples
        d_loss = self.discriminator_loss(x)

        tqdm_dict = {'d_loss': d_loss}
        output = OrderedDict({
            'loss': d_loss,
            'progress_bar': tqdm_dict,
            'log': tqdm_dict
        })
        return output

    def training_step(self, batch, batch_idx, optimizer_idx):
        x, _ = batch
        self.last_imgs = x

        # train generator
        if optimizer_idx == 0:
            return self.generator_step(x)

        # train discriminator
        if optimizer_idx == 1:
            return self.discriminator_step(x)

    def configure_optimizers(self):
        lr = self.learning_rate
        b1 = self.b1
        b2 = self.b2

        opt_g = torch.optim.Adam(self.generator.parameters(), lr=lr, betas=(b1, b2))
        opt_d = torch.optim.Adam(self.discriminator.parameters(), lr=lr, betas=(b1, b2))
        return [opt_g, opt_d], []

    def prepare_data(self):
        self.dataloaders.prepare_data()

    def train_dataloader(self):
        return self.dataloaders.train_dataloader(self.batch_size)

    @staticmethod
    def add_model_specific_args(parent_parser):
        parser = ArgumentParser(parents=[parent_parser], add_help=False)
        parser.add_argument('--input_width', type=int, default=28,
                            help='input image width - 28 for MNIST (must be even)')
        parser.add_argument('--input_channels', type=int, default=1,
                            help='num channels')
        parser.add_argument('--input_height', type=int, default=28,
                            help='input image height - 28 for MNIST (must be even)')
        parser.add_argument('--learning_rate', type=float, default=0.0002, help="adam: learning rate")
        parser.add_argument('--b1', type=float, default=0.5,
                            help="adam: decay of first order momentum of gradient")
        parser.add_argument('--b2', type=float, default=0.999,
                            help="adam: decay of first order momentum of gradient")
        parser.add_argument('--latent_dim', type=int, default=100,
                            help="generator embedding dim")
        parser.add_argument('--batch_size', type=int, default=64, help="size of the batches")

        return parser


if __name__ == '__main__':
    parser = ArgumentParser()
    parser = Trainer.add_argparse_args(parser)
    parser = GAN.add_model_specific_args(parser)
    args = parser.parse_args()

    save_folder = 'model_weights/'
    if not os.path.exists(save_folder):
        os.mkdir(save_folder)
    early_stopping = EarlyStopping('avg_val_loss')
    # saves checkpoints to 'save_folder' whenever 'val_loss' has a new min
    checkpoint_callback = ModelCheckpoint(
                            filepath=save_folder+'model_{epoch:02d}-{val_loss:.2f}')
    tb_logger = loggers.TensorBoardLogger('logs/')


    gan = GAN(args)
    trainer = Trainer(checkpoint_callback=checkpoint_callback,
                        early_stop_callback=early_stopping,
                        fast_dev_run=False,                      # make this as True only to check for bugs
                        max_epochs=1000,
                        resume_from_checkpoint=None,            # change this to model_path
                        logger=tb_logger,                       # tensorboard logger
                        )
    trainer.fit(gan)
    trainer.test()