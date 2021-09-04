# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
"""
DETR model and criterion classes.
"""
import torch
import torch.nn.functional as F
from torch import nn
import numpy as np

from .backbone import build_backbone
from .query_generate import build_query
# from .query_generate_dct_phoc import encode_input_string_new as build_query

# from .transformer_full import build_transformer
# from .transformer_decoder import build_transformer_decoder
from .decoder import build_transformer_decoder
from .utils import CTCLabelConverter
import gin


class QUESTER(nn.Module):
    """ This is the QUESTER module that performs scene text retireval """
    def __init__(self, backbone, transformer, query_gen, query_len, num_queries, aux_loss=False):
        """ the Initializes model.
        Parameters:
            backbone: torch module of the backbone to be used. See backbone.py
            transformer: torch module of the transformer architecture. See transformer.py
            num_classes: number of object classes
            num_queries: number of object queries, ie detection slot. This is the maximal number of objects
                         QUESTER can detect in a single image.
            aux_loss: True if auxiliary decoding losses (loss at each decoder layer) are to be used.
        """
        super().__init__()
        self.num_queries = num_queries
        self.query_gen = query_gen
        self.transformer = transformer
        hidden_dim = transformer.d_model
        self.confidence_embed = MLP(hidden_dim, hidden_dim, 1, 3)
        self.query_embed = nn.Embedding(num_queries, hidden_dim)

        self.backbone = backbone
        self.aux_loss = aux_loss

    def forward(self, samples, target):

        features, pos = self.backbone(samples) # N 1100 512
        query_items, _ = self.query_gen(target)
        # print(f"features.shape: {features.shape}")
        # print(f"pos.shape: {pos.shape}")
        # print(f"query_items.shape: {query_items.shape}")
        # print(f"self.query_embed.weight.shape: {self.query_embed.weight.shape}")
        query_embed_weight = self.query_embed.weight.reshape((query_items.shape[1],
                                                             query_items.shape[2],
                                                             query_items.shape[3]))
        # print(f"query_embed_weight.shape: {query_embed_weight.shape}")
        hs = self.transformer(features, query_items, query_embed_weight, pos)[0]

        output_confidence = self.confidence_embed(hs).sigmoid()
        out = {'score': output_confidence, 'context': hs}
        if self.aux_loss:
            out['aux_outputs'] = self._set_aux_loss(outputs_class, outputs_coord)
        return out

    @torch.jit.unused
    def _set_aux_loss(self, outputs_class, outputs_coord):
        # this is a workaround to make torchscript happy, as torchscript
        # doesn't support dictionary with non-homogeneous values, such
        # as a dict having both a Tensor and a list.
        return [{'pred_logits': a, 'pred_boxes': b}
                for a, b in zip(outputs_class[:-1], outputs_coord[:-1])]


class SetCriterion(nn.Module):

    def __init__(self, ralph, losses):

        super().__init__()
        self.losses = losses
        self.converter = CTCLabelConverter(ralph)

    def loss_score(self, outputs, targets):
        """Classification loss (NLL)
        targets dicts must contain the key "labels" containing a tensor of dim [nb_target_boxes]
        """
        assert 'score' in outputs
        src_scores = outputs['score']

        tmp = []
        target_text, target_scores = targets
        for i in target:
            tmp.append(torch.FloatTensor(i).unsqueeze(0))
        target_scores_tensor = torch.cat(tmp)

        loss_score = F.cross_entropy(src_scores, target_scores)
        losses = {'loss_score': loss_score}

        return losses

    def filter_mask(self, outputs, targets):

        target_txt, target_mask = targets
        index_list = []
        target_txt_final = []
        outputs_list = []
        for txt_item, mask_item in zip(target_txt, target_mask):
            index = [i for i, e in enumerate(mask_item) if e != 0]
            index_list.append(index)
            target_txt_final.append(txt_item[t] for t in index)

        for outputs_item, index_item in zip(outputs, index_list):
            outputs_list.append(outputs_item[index_item])

        return outputs_list, target_txt_final

    def loss_text(self, outputs, targets):

        assert 'context' in outputs
        ctc_loss = torch.nn.CTCLoss(reduction='none', zero_infinity=True)
        src_context = outputs['context'] # (N, query_num, query_len, dim)
        N = src_context.shape[0]
        outputs_list, target_list = self.filter_mask(src_context, targets)
        # target_context_list = [x.split(";:") for x in targets]
        loss_all = 0
        for pre_item, tar_item in zip(outputs_list, target_list):
            item_drop_permute = pre_item.permute(1, 0, 2) # query_len, num, dim
            text, length = self.convert.encode(tar_item)
            preds_size = torch.IntTensor([item_drop_permute.shape[1]] * item_drop_permute.shape[0])
            loss_item = ctc_loss(item_drop_permute,
                                 text,
                                 preds_size,
                                 length
                                 ).mean()
            loss_all += loss_item


        losses['loss_text'] = loss_all / N

        return losses

    def drop_zero_column(self, input):

        valid_cols = []
        for col_idx in range(input.size(1)):
            if not torch.all(input[col_idx, :] == 0):
                valid_cols.append(col_idx)
        A = input[valid_cols, :]

        return A


    def get_loss(self, loss, outputs, targets):
        loss_map = {
            'score': self.loss_score,
            'text': self.loss_text,
        }
        assert loss in loss_map, f'do you really want to compute {loss} loss?'
        return loss_map[loss](outputs, targets)

    def forward(self, outputs, targets):

        # Compute all the requested losses
        losses = {}
        for loss in self.losses:
            losses.update(self.get_loss(loss, outputs, targets))

        return losses


class MLP(nn.Module):
    """ Very simple multi-layer perceptron (also called FFN)"""

    def __init__(self, input_dim, hidden_dim, output_dim, num_layers):
        super().__init__()
        self.num_layers = num_layers
        h = [hidden_dim] * (num_layers - 1)
        self.layers = nn.ModuleList(nn.Linear(n, k) for n, k in zip([input_dim] + h, h + [output_dim]))

    def forward(self, x):
        for i, layer in enumerate(self.layers):
            x = F.relu(layer(x)) if i < self.num_layers - 1 else layer(x)
        return x


def get_alph(path):

    alph = np.load(path, allow_pickle='True').item()

    return alph.values()

@gin.configurable
def build_quester(device, query_len, num_queries):

    path = '/home/zju/w4/STR_e2e/ic15/alph.npy'

    backbone = build_backbone()
    # transformer = build_transformer(args)
    transformer = build_transformer_decoder()
    # query_gen = build_query()
    query_gen = build_query

    model = QUESTER(
        backbone,
        transformer,
        query_gen,
        query_len,
        num_queries=num_queries,
    )


    losses = ['score', 'text']

    criterion = SetCriterion(ralph=get_alph(path), losses=losses)
    criterion.to(device)

    return model, criterion
