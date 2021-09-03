'''
input: ['abdad;:fas;:dfas', 'asdfa;:asfas']
output: (N, query_num, emb_len)
'''
import torch
import torch.nn as nn
import torch.nn.functional as F

import math
import numpy as np

from transformers import AutoTokenizer, AutoModel
import gin


device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

@gin.configurable
class TextEncoder(nn.Module):
    '''
    input: string with maxlen
    output: N*80 dim
    '''
    def __init__(self, bert_base_model, out_dim, freeze_layers):
        super().__init__()
        #init BERT
        self.bert_model = self._get_bert_basemodel(bert_base_model,freeze_layers)
        self.tokenizer = AutoTokenizer.from_pretrained(bert_base_model, cache_dir='./cached')
        # projection MLP for BERT model
        self.bert_l1 = nn.Linear(768, 768) #768 is the size of the BERT embbedings
        self.bert_l2 = nn.Linear(768, out_dim) #768 is the size of the BERT embbedings

    def _get_bert_basemodel(self, bert_model_name, freeze_layers):
        try:
            model = AutoModel.from_pretrained(bert_model_name)#, return_dict=True)
            print("text feature extractor:", bert_model_name)
        except:
            raise ("Invalid model name. Check the config file and pass a BERT model from transformers lybrary")

        if freeze_layers is not None:
            for layer_idx in freeze_layers:
                for param in list(model.encoder.layer[layer_idx].parameters()):
                    param.requires_grad = False
        return model

    def mean_pooling(self, model_output, attention_mask):

        token_embeddings = model_output[0] #First element of model_output contains all token embeddings
        # print(f"token_embeddings.shape: {token_embeddings.shape}")
        # print(f"attention_mask.shape: {attention_mask.shape}")
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        # print(f"input_mask_expanded.shape: {input_mask_expanded.shape}")
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)

        # print(f"sum_embeddings.shape: {sum_embeddings.shape}")
        # print(f"sum_embeddings.shape: {sum_embeddings.shape}")
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)

        return sum_embeddings / sum_mask

    def split_input(self, input_target):
        '''
        input like: ['abc;;;def','ksdf;;;asfdas;;;asdfa']
        '''
        split_list = [t.split(";:") for t in input_target]

        return split_list

    def encoder(self, encoded_inputs):

        encoded_inputs_tokens = self.tokenizer(encoded_inputs,
                                               return_tensors="pt",
                                               padding=True,
                                               truncation=False) #.to(device)

        outputs = self.bert_model(**encoded_inputs_tokens)

        with torch.no_grad():
            sentence_embeddings = self.mean_pooling(outputs, encoded_inputs_tokens['attention_mask'])

        x = self.bert_l1(sentence_embeddings)
        x = F.relu(x)
        out_emb = self.bert_l2(x)

        return out_emb

    def forward(self, encoded_inputs):

        output_list = []
        output_list_mask = []

        target_list, mask_list = encoded_inputs[0], encoded_inputs[1]

        for target_item, mask_item in zip(target_list, mask_list):
            item_out = self.encoder(list(target_item))
            output_list.append(item_out.unsqueeze(0))
            mask_item_torch = torch.from_numpy(np.array(mask_item))
            output_list_mask.append(mask_item_torch.unsqueeze(0))

        #zls = zls.unsqueeze(-1).repeat(1, 1, dims)
        zls = torch.cat(output_list)
        zls_mask = torch.cat(output_list_mask)
        return zls, zls_mask


def build_query():

    query_gen = TextEncoder()

    return query_gen

if __name__ == "__main__":

    input =  ([('', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', '', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', '', '', 'L', '', 'L', 'L', 'L', 'L', '', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L'), ('', '', '', '', '', '', '', '', '', 'L', '', '', '', 'L', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'L', 'L', '', '', '', '', '', 'L', '', '', '', 'L', '', '', '', '', '', ''), ('L', 'L', '', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', '', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', '', '', 'L', 'L', 'L', 'L', 'L', 'L', '', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', 'L', '', 'L')],[(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0)])
    config_file = "./test/query_gen_bert.gin"
    gin.parse_config_file(config_file)

    query_gen = TextEncoder()

    out = query_gen(input)
    print(out[0].shape)
    print(out[1])
