"""
This file is for getting BERT
and RoBERTa substitutes for adjectives
in Wikipedia sentences.

Some code modified from (Bill) Yuchen Lin's example:
https://gist.github.com/yuchenlin/a2f42d3c4378ed7b83de65c7a2222eb2
"""
import torch
from transformers import BertTokenizerFast, RobertaTokenizerFast, BertForMaskedLM, RobertaForMaskedLM
from tqdm import tqdm
import time
import json
from collections import defaultdict, Counter

ROOT = '/mnt/data0/lucy/manosphere/'
DATA = ROOT + 'data/'
LOGS = ROOT + 'logs/'

def predict_masked_sent(model_name, batch_sentences, batch_idx, batch_metadata, tokenizer, top_k=20):
    '''
    Produces an output file where each line is
    "line_ID adjective substitute1 substitute2 subsitute3 ...." 
    '''
    if model_name == 'bert-base-uncased' or model_name == 'bert-large-uncased': 
        model = BertForMaskedLM.from_pretrained(model_name)
    elif model_name == "roberta-base": 
        model = RobertaForMaskedLM.from_pretrained(model_name)
        
    model.eval()
    model.to('cuda')
    
    with open(LOGS + 'wikipedia/substitutes/' + model_name + '.csv', 'w') as outfile: 
        for b, batch in enumerate(tqdm(batch_sentences)): 
            masked_index = batch_idx[b]
            encoded_inputs = tokenizer(batch, padding=True, truncation=True, 
                 return_tensors="pt")
            encoded_inputs.to("cuda")

            # Predict all tokens
            with torch.no_grad():
                outputs = model(**encoded_inputs)
                predictions = outputs['logits'] # [batch_size, seq_length, vocab_size]

            probs = torch.nn.functional.softmax(predictions[0, masked_index], dim=-1) # [batch_size, vocab_size]
            top_k_weights, top_k_indices = torch.topk(probs, top_k, sorted=True) # [batch_size, k]

            for i, pred_idx in enumerate(top_k_indices):
                predicted_tokens = tokenizer.convert_ids_to_tokens(pred_idx)
                line_ID, adj = batch_metadata[b][i]
                outfile.write(line_ID + ' ' + adj + ' ' + ' '.join(predicted_tokens) + '\n')
                
def get_masked_probs(keywords, model_name, batch_sentences, batch_idx, batch_metadata, tokenizer):
    '''
    @inputs
    - keywords: { adj : {synset_syn / synset_ant : [synonym or antonyms] } }
    - model_name: string that is the name of the model
    - batch_sentences: list of list of strings
    - batch_idx: list of list of index of the masked token
    - batch_metadata: list of list of (line_ID, adj)
    Produce an output file where each line is
    "line_ID adjective synonym|prob synonym|prob ... antonym|prob antonym|prob
    '''
    if model_name == 'bert-base-uncased' or model_name == 'bert-large-uncased': 
        model = BertForMaskedLM.from_pretrained(model_name)
    elif model_name == "roberta-base": 
        model = RobertaForMaskedLM.from_pretrained(model_name)
        
    model.eval()
    model.to('cuda')
    
    with open(LOGS + 'wikipedia/wordnet_probs/' + model_name + '.csv', 'w') as outfile: 
        for b, batch in enumerate(tqdm(batch_sentences)): 
            masked_index = batch_idx[b]
            encoded_inputs = tokenizer(batch, padding=True, truncation=True, 
                 return_tensors="pt")
            encoded_inputs.to("cuda")

            # Predict all tokens
            with torch.no_grad():
                outputs = model(**encoded_inputs)
                predictions = outputs['logits'] # [batch_size, seq_length, vocab_size]

            probs = torch.nn.functional.softmax(predictions[0, masked_index], dim=-1) # [batch_size, vocab_size]
            
            for i, i_probs in enumerate(probs): 
                line_ID, adj = batch_metadata[b][i]
                kws = keywords[adj]
                for side in kws: 
                    kws_side = kws[side]
                    output_line = []
                    for kw in kws_side: 
                        weight = i_probs[kw]
                        output_line.append(str(kw) + '_' + str(weight.item()))
                    outfile.write(side + ' ' + line_ID + ' ' + adj + ' ' + ' '.join(output_line) + '\n')
        
def batch_data(lines_adj, tokenizer): 
    num_lines = len(lines_adj)
    start = time.time()
    batch_size = 8
    batch_sentences = [] # list of batches
    batch_idx = [] 
    batch_metadata = [] 
    curr_batch = [] # list of list of tokens
    curr_idx = [] # list of masked_index
    curr_metadata = [] # (line_ID, adj)
    with open(LOGS + 'wikipedia/adj_data/part-00000', 'r') as infile: 
        for line in tqdm(infile, total=num_lines):
            contents = line.split('\t')
            line_num = contents[0]
            text = '\t'.join(contents[1:]).lower()
            words_in_line = lines_adj[line_num]
            
            tokens = tokenizer.tokenize(text) # wordpiece tokens
            for adj in words_in_line: 
                adj_tokens = tokenizer.tokenize(adj)
                adj_len = len(adj_tokens)
                for i in range(len(tokens)): 
                    if tokens[i:i+adj_len] == adj_tokens: 
                        new_tokens = tokens[:i] + ["[MASK]"] + tokens[i+adj_len:]
                        curr_batch.append(tokenizer.convert_tokens_to_string(new_tokens))
                        curr_idx.append(i)
                        curr_metadata.append((line_num, adj))
                        if len(curr_batch) == batch_size: 
                            batch_sentences.append(curr_batch)
                            batch_idx.append(curr_idx)
                            batch_metadata.append(curr_metadata)
                            curr_batch = []
                            curr_idx = []
                            curr_metadata = []
                        break # target word found
    if len(curr_batch) != 0: # fence post
        batch_sentences.append(curr_batch)
        batch_idx.append(curr_idx)
        batch_metadata.append(curr_metadata)
        
    print("TIME:", time.time() - start)
    return batch_sentences, batch_idx, batch_metadata

def get_lines_adj(): 
    with open(LOGS + 'wikipedia/adj_lines.json', 'r') as infile: 
        adj_lines = json.load(infile) # {adj : [line IDs]}
        
    lines_adj = defaultdict(list) # {line ID: [adj]}
    for adj in adj_lines: 
        for line in adj_lines[adj]: 
            lines_adj[str(line)].append(adj.replace('xqxq', '-'))
    return lines_adj

def get_tokenizer(model_name): 
    if model_name == 'bert-base-uncased' or model_name == 'bert-large-uncased': 
        tokenizer = BertTokenizerFast.from_pretrained(model_name)
    elif model_name == "roberta-base":
        tokenizer = RobertaTokenizerFast.from_pretrained(model_name)
    return tokenizer

def predict_substitutes(model_name): 
    lines_adj = get_lines_adj()
    tokenizer = get_tokenizer(model_name)
            
    print("Getting batches...")
    batch_sentences, batch_idx, batch_metadata = batch_data(lines_adj, tokenizer)
    
    predict_masked_sent(model_name, batch_sentences, batch_idx, batch_metadata, tokenizer)
    
def predict_substitute_probs(model_name): 
    lines_adj = get_lines_adj()     
    tokenizer = get_tokenizer(model_name)
            
    print("Getting batches...")
    batch_sentences, batch_idx, batch_metadata = batch_data(lines_adj, tokenizer)
    
    print("Getting keywords...")
    keywords = defaultdict(dict) # { adj : {synset_syn / synset_ant : [synonym or antonyms] } }
    with open(LOGS + 'semantics_val/wordnet_axes.txt', 'r') as infile: 
        for line in infile: 
            contents = line.strip().split('\t') 
            if len(contents) < 3: continue # no antonyms
            synset = contents[0]
            axis1 = set(contents[1].split(','))
            axis2 = set(contents[2].split(','))
            axis1_idx = []
            for w in axis1: 
                toks = tokenizer.tokenize(w)
                if len(toks) == 1: # keep whole words only
                    idx = tokenizer.convert_tokens_to_ids(toks)[0]
                    axis1_idx.append(idx)
            axis2_idx = []
            for w in axis2: 
                toks = tokenizer.tokenize(w)
                if len(toks) == 1: 
                    idx = tokenizer.convert_tokens_to_ids(toks)[0]
                    axis2_idx.append(idx)
            for adj in axis1: 
                keywords[adj][synset + '_syn'] = axis1_idx
                keywords[adj][synset + '_ant'] = axis2_idx
            for adj in axis2: 
                keywords[adj][synset + '_syn'] = axis2_idx
                keywords[adj][synset + '_ant'] = axis1_idx
    
    get_masked_probs(keywords, model_name, batch_sentences, batch_idx, batch_metadata, tokenizer)
    
def get_syn_ant(): 
    # get mapping from each word to its synonyms and antonyms
    synonyms = defaultdict(dict) # {adj : {synset: [synonyms]} }
    antonyms = defaultdict(dict)
    with open(LOGS + 'semantics_val/wordnet_axes.txt', 'r') as infile: 
        for line in infile: 
            contents = line.strip().split('\t') 
            if len(contents) < 3: continue # no antonyms
            synset = contents[0]
            axis1 = set(contents[1].split(','))
            axis2 = set(contents[2].split(','))
            for adj in axis1: 
                synonyms[adj][synset + '_left'] = axis1
                antonyms[adj][synset + '_left'] = axis2
            for adj in axis2: 
                synonyms[adj][synset + '_right'] = axis2
                antonyms[adj][synset + '_right'] = axis1
    return synonyms, antonyms

def find_good_contexts_probs(model_name): 
    '''
    The output of this function is the same format as adj_lines_random.json
    in wikipedia_embeddings.py. {line_num: [(adj, synset)]}
    '''
    synonyms, antonyms = get_syn_ant()
    
    syn_scores = defaultdict(dict) # { synset_side : { line_ID_adj: [scores] } }
    syn_subs = defaultdict(dict) # { synset_side : { line_ID_adj: [subs] } } where subs in same order as scores
    ant_scores = defaultdict(dict)
    ant_subs = defaultdict(dict)
    c = 0
    with open(LOGS + 'wikipedia/wordnet_probs/' + model_name + '.csv', 'r') as infile: 
        for line in infile: 
            if c % 1000000 == 0: 
                print("Read in", c, "lines")
            c += 1
            contents = line.strip().split(' ')
            line_num = contents[1]
            adj = contents[2] 
            subs = []
            scores = []
            if len(contents) > 3: 
                for i in range(3, len(contents)): 
                    item = contents[i].split('_')
                    scores.append(float(item[1]))
                    subs.append(item[0])
            synset_a_s = contents[0].split('_')
            synset = synset_a_s[0]
            if synset + '_left' in synonyms[adj]: 
                synset_side = synset + '_left'
            if synset + '_right' in synonyms[adj]: 
                synset_side = synset + '_right'
            if synset_side[1] == 'syn': 
                syn_scores[synset_side][line_num + '_' + adj] = scores
                syn_subs[synset_side][line_num + '_' + adj] = subs
            if synset_side[1] == 'ant': 
                ant_scores[synset_side][line_num + '_' + adj] = scores
                ant_subs[synset_side][line_num + '_' + adj] = subs
    
    c = 0
    for synset_side in tqdm(syn_scores): 
        if not synset.startswith('strong.a.01') and not synset.startswith('violent.a.01'): 
            continue
        print(synset)
        syn_avg_scores = Counter()
        for line_num_adj in syn_scores[synset_side]: 
            scores = syn_scores[synset_side][line_num_adj]
            syn_avg_scores[line_num_adj] = sum(scores) / len(scores)
        top_200 = syn_avg_scores.most_common(200)
        syn_ant_diff = Counter()
        for tup in top_200: 
            line_num_adj, score = tup
            scores = ant_scores[synset_side][line_num_adj]
            diff = syn_avg_scores[line_num_adj] - sum(scores) / len(scores)
            syn_ant_diff[line_num_adj] = diff
        top_100 = syn_ant_diff.most_common(100)
        for tup in top_100: 
            print(tup)
        print()
        
        c += 1
        if c > 10: break
        
        # for every adj in synset on either side
            # if adj in syn or ant score calculation, subtract its score from total
            # do not look at contexts where this adj is masked out word
            # get the top 200 contexts by syn scores
            # get the top 100 contexts where syn-ant is maximized 
            # keep track of contexts associated with this loov: synset + '_' + line_ID + '_' + adj 
            # add sentence to total set of sentences to run model on
    
def find_good_contexts_subs(model_name):
    """
    This is called before inspect_contexts().
    The output of this function is the same format as adj_lines_random.json
    in wikipedia_embeddings.py.
    """
    synonyms, antonyms = get_syn_ant()
    
    good_line_scores = defaultdict(tuple)
    bad_line_scores = defaultdict(tuple)
    singleton_subs = defaultdict(list) # {synset + '_' + line_ID + '_' + adj : [substitutes]}
    total = 0
    good_score_counts = Counter()
    with open(LOGS + 'wikipedia/substitutes/' + model_name + '.csv', 'r') as infile: 
        for line in infile: 
            contents = line.split(' ')
            line_ID = contents[0]
            adj = contents[1]
            preds = set(contents[2:])
            for synset in antonyms[adj]: 
                total += 1
                ant_overlap = preds & antonyms[adj][synset]
                if len(ant_overlap) > 0: 
                    bad_line_scores[(line_ID, adj, synset)] = (len(ant_overlap), ant_overlap)
                    continue
                syn_overlap = preds & synonyms[adj][synset]
                if len(syn_overlap) == 0: continue
                if len(syn_overlap) == 1: 
                    # one substitute is the reason for overlap, should take in account for LOOV
                    sub_word = list(syn_overlap)[0]
                    singleton_subs[synset + '_' + line_ID + '_' + adj].append(sub_word)
                score = len(syn_overlap)
                good_score_counts[score] += 1
                good_line_scores[(line_ID, adj, synset)] = (score, syn_overlap)

    print(len(good_line_scores), total)
    print(good_score_counts.most_common())
    print()
    print(len(bad_line_scores), total)
    print()
    
    adj_lines = defaultdict(list)
    for tup in good_line_scores: 
        line_ID, adj, synset = tup
        adj_lines[line_ID].append([adj, synset])
        
    print("ADJ LINES LENGTH:", len(adj_lines))
        
    if model_name == 'bert-base-uncased': 
        outfile_name = 'adj_lines_base-substitutes.json'
        subfile_name = 'sub_lines_base-substitutes.json'
    elif model_name == 'bert-large-uncased': 
        outfile_name = 'adj_lines_large-substitutes.json'
        subfile_name = 'sub_lines_large-substitutes.json'
        
    with open(LOGS + 'wikipedia/' + outfile_name, 'w') as outfile: 
        json.dump(adj_lines, outfile)
        
    with open(LOGS + 'wikipedia/' + subfile_name, 'w') as outfile: 
        json.dump(singleton_subs, outfile)
        
def inspect_contexts(model_name): 
    '''
    This needs to be called after find_good_contexts(). 
    Some axis sides have no adj that have good contexts, 
    in which case we will just use the random lines 
    version of the context.
    '''
    if model_name == 'bert-base-uncased': 
        infile_name = 'adj_lines_base-substitutes.json'
    elif model_name == 'bert-large-uncased': 
        infile_name = 'adj_lines_large-substitutes.json'
    
    with open(LOGS + 'wikipedia/' + infile_name, 'r') as infile: 
        adj_lines = defaultdict(list, json.load(infile)) # {line_num: [(adj, synset)]}
        
    all_synsets = {}
    with open(LOGS + 'semantics_val/wordnet_axes.txt', 'r') as infile: 
        for line in infile: 
            contents = line.strip().split('\t') 
            if len(contents) < 3: continue # no antonyms
            synset = contents[0]
            axis1 = set(contents[1].split(','))
            axis2 = set(contents[2].split(','))
            all_synsets[synset + '_left'] = axis1
            all_synsets[synset + '_right'] = axis2
            
    synset_counts = {}
    for ss in all_synsets: 
        synset_counts[ss] = 0
        
    for line_ID in adj_lines: 
        for tup in adj_lines[line_ID]: 
            synset = tup[1]
            synset_counts[synset] += 1
            
    synset_counts = Counter(synset_counts)
    one_empty_count = 0
    all_empty_count = 0
    for ss in all_synsets: 
        if 'left' in ss: 
            other_ss = ss.replace('left', 'right')
        elif 'right' in ss: 
            continue
        if synset_counts[ss] == 0 or synset_counts[other_ss] == 0:
            if synset_counts[ss] == 0 and synset_counts[other_ss] == 0: 
                all_empty_count += 1
            else: 
                one_empty_count += 1
            print(ss, synset_counts[ss], synset_counts[other_ss])

    print("Axis all empty:", all_empty_count)
    print("Axis one side empty:", one_empty_count)

def main(): 
    #predict_substitutes('bert-base-uncased')
    #predict_substitutes('bert-large-uncased')
    #predict_substitute_probs('bert-base-uncased')
    # TODO: roberta is broken currently due to tokenization issues
    #predict_substitutes('roberta-base')
    #find_good_contexts_subs('bert-base-uncased')
    #find_good_contexts_subs('bert-large-uncased')
    find_good_contexts_probs('bert-base-uncased')
    #inspect_contexts('bert-base-uncased')
    #inspect_contexts('bert-large-uncased')

if __name__ == '__main__':
    main()