"""
Various helper functions
"""
import csv
from collections import Counter, defaultdict
from transformers import BasicTokenizer
import os
import json
import re
from pyspark import SparkConf, SparkContext
from pyspark.sql import SQLContext
from functools import partial
import sys
import time
import math

ROOT = '/mnt/data0/lucy/manosphere/'
#ROOT = '/global/scratch/lucy3_li/manosphere/'
COMMENTS = ROOT + 'data/comments/'
POSTS = ROOT + 'data/submissions/'
PEOPLE_FILE = ROOT + 'data/people.csv'
NONPEOPLE_FILE = ROOT + 'data/non-people.csv'
LOGS = ROOT + 'logs/'
UD = LOGS + 'urban_dict.csv'
WORD_COUNT_DIR = LOGS + 'gram_counts/'

def get_manual_people(): 
    """
    get list of words, add plural forms
    """
    words = set()
    sing2plural = {}
    with open(PEOPLE_FILE, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            word_sing = row['word (singular)'].strip()
            plural = row['word (plural)'].strip()
            if word_sing != '':
                if word_sing.lower() in words: print('REPEAT', word_sing)
                words.add(word_sing.lower())
                sing2plural[word_sing.lower()] = plural.lower()
            if plural != '': 
                if plural.lower() in words: print('REPEAT', plural)
                assert word_sing != ''
                words.add(plural.lower())
    return words, sing2plural

def get_manual_nonpeople(): 
    words = set()
    with open(NONPEOPLE_FILE, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['community'].strip() != 'generic': 
                word = row['word']
                if word != '':
                    if word.lower() in words: print('REPEAT', word)
                    words.add(word.lower())
    return words

def calculate_ud_coverage(): 
    """
    see how many common nouns for people turn up in urban dictionary
    """
    people, sing2plural = get_manual_people()
    num_definitions = Counter()
    with open(UD, 'r') as infile: 
        for line in infile: 
            contents = line.strip().split('|')
            word = contents[0].lower()
            if word in people: 
                num_definitions[word] += 1
    missing_count = 0
    for w in sing2plural: 
        if num_definitions[w] == 0: 
            if num_definitions[sing2plural[w]] == 0: 
                missing_count += 1
    print("Total number of people:", len(sing2plural))
    print("Missing:", missing_count)
    print("Number of definitions:", num_definitions.values())
    
def get_term_count_comment(line, all_terms=None): 
    '''
    Returns a list where keys are subreddits and terms and values
    are counts
    This is for exact string matches, and is slightly deprecated because
    we have a faster token counter using BERT BasicTokenizer elsewhere. 
    '''
    d = json.loads(line)
    if 'body' not in d: 
        return []
    text = d['body'].lower()
    sr = d['subreddit'].lower()
    term_counts = Counter()
    for term in all_terms: 
        res = re.findall(r'\b' + re.escape(term) + r'\b', text)
        term_counts[term] += len(res)
    ret = []
    for term in term_counts: 
        ret.append(((sr, term), term_counts[term]))
    return ret 

def get_term_count_post(line, all_terms=None): 
    d = json.loads(line)
    if 'selftext' not in d: 
        return []
    text = d['selftext'].lower()
    sr = d['subreddit'].lower()
    term_counts = Counter()
    for term in all_terms:
        res = re.findall(r'\b' + re.escape(term) + r'\b', text)
        term_counts[term] += len(res)
    ret = []
    for term in term_counts: 
        ret.append(((sr, term), term_counts[term]))
    return ret 

def count_words_reddit_parallel(): 
    """
    This is an exact string matcher, and we have another token
    counter elsewhere, so this is deprecated. 
    """
    all_terms, _ = get_manual_people()
    f = sys.argv[1]
    month = f.replace('RC_', '')
    term_counts = defaultdict(Counter)
    with open(COMMENTS + f + '/part-00000', 'r') as infile: 
        for line in infile: 
            d = json.loads(line)
            if 'body' not in d: continue
            text = d['body'].lower()
            sr = d['subreddit'].lower()
            for term in all_terms: 
                res = re.findall(r'\b' + re.escape(term) + r'\b', text)
                term_counts[sr][term] += len(res)

    if os.path.exists(POSTS + 'RS_' + month + '/part-00000'): 
        post_path = POSTS + 'RS_' + month + '/part-00000'
    else: 
        post_path = POSTS + 'RS_v2_' + month + '/part-00000'
    with open(post_path, 'r') as infile: 
        for line in infile: 
            d = json.loads(line)
            if 'selftext' not in d: continue
            text = d['selftext'].lower()
            sr = d['subreddit'].lower()
            for term in all_terms:
                res = re.findall(r'\b' + re.escape(term) + r'\b', text)
                term_counts[sr][term] += len(res)
    with open(LOGS + 'glossword_time_place/' + month + '.json', 'w') as outfile: 
        json.dump(term_counts, outfile)

def save_occurring_glosswords(): 
    '''
    Save only glossary words that actually appear in the text, 
    print out ones that do not appear. 
    '''
    words = Counter()
    all_words = set()
    for f in os.listdir(LOGS + 'glossword_time_place/'): 
        with open(LOGS + 'glossword_time_place/' + f, 'r') as infile: 
            counts = json.load(infile)
            for sr in counts: 
                for w in counts[sr]: 
                    all_words.add(w)
                    if counts[sr][w] != 0: 
                        words[w] += counts[sr][w]
    print("Missing glossary words:")
    num_missing = 0
    for w in sorted(all_words): 
        if w not in words: 
            print(w)
            num_missing += 1
    print("Number of missing", num_missing, "out of", len(all_words), "words")
    with open(LOGS + 'glossword_counts.json', 'w') as outfile: 
        json.dump(words, outfile)
        
def get_term_count_tagged(line, all_terms=None):
    '''
    Right now this only works on Reddit tags
    '''
    entities = line.strip().split('\t')
    sr = entities[0]
    text = '\t'.join(entities[1:]) 
    term_counts = Counter()
    for term in all_terms: 
        res = re.findall(r'\b' + re.escape(term) + r'\b', text)
        term_counts[term] += len(res)
    ret = []
    for term in term_counts: 
        ret.append((sr + '$' + term, term_counts[term]))
    return ret
        
def count_glosswords_in_tags(): 
    '''
    For every glossary word, count how much it occurs in tagged spans

    TODO: this needs to be rewritten with new tagger results.
    '''
    all_terms, _ = get_manual_people()
    data = sc.textFile(LOGS + 'all_tagged_people')
    data = data.flatMap(partial(get_term_count_tagged, all_terms=all_terms))
    data = data.reduceByKey(lambda n1, n2: n1 + n2)
    data = data.collectAsMap()
    with open(LOGS + 'tagged_glossword_counts.json', 'w') as outfile: 
        json.dump(data, outfile)
        
def get_ngrams_glosswords(): 
    '''
    Get number of tokens in glossary words, 
    to see what we are missing if we only use bigrams and unigrams. 
    '''
    all_terms, _ = get_manual_people()
    num_tokens = defaultdict(list)
    for w in all_terms: 
        num_tokens[len(w.split())].append(w)
    print(num_tokens.keys())
    print(num_tokens[5], num_tokens[4], num_tokens[3])
    
def get_sr_cats(): 
    categories = defaultdict(str)
    with open(ROOT + 'data/subreddits.txt', 'r') as infile: 
        reader = csv.DictReader(infile)
        for row in reader: 
            name = row['Subreddit'].strip().lower()
            if name.startswith('/r/'): name = name[3:]
            if name.startswith('r/'): name = name[2:]
            if name.endswith('/'): name = name[:-1]
            categories[name] = row['Category after majority agreement']
    return categories

def load_gram_counts(categories, sqlContext): 
    df = sqlContext.read.parquet(WORD_COUNT_DIR + 'subreddit_counts')
    leave_out = []
    for sr in categories: 
        if categories[sr] == 'Health' or categories[sr] == 'Criticism': 
            leave_out.append(sr)
    df = df.filter(~df.community.isin(leave_out))
    return df

def update_gram_counts(line, categories, tokenizer, deps, depheads, gram_counts, reddit=True): 
    content = line.split('\t')
    entities = content[1:]
    if reddit: 
        sr = content[0]
        cat = categories[sr.lower()]
        if cat == 'Health' or cat == 'Criticism': continue
    for entity in entities: 
        if entity.strip() == '': continue
        tup = entity.lower().split(' ')
        label = tup[0]
        start = int(tup[1])
        end = int(tup[2])
        head = int(tup[3])
        phrase = ' '.join(tup[4:])
        phrase = tokenizer.tokenize(phrase)
        if truncate: 
            phrase_start = 0
            # calculate phrase start, excluding determiner or possessive dep on root
            deprel = deps[str(i)][tup[1]]
            dephead = depheads[str(i)][tup[1]]
            if (deprel == 'poss' or deprel == 'det') and dephead == head: 
                phrase_start = 1
            # get bigrams and unigrams from start to root
            if (1 + head - start) - phrase_start in set([1, 2]): 
                other_phrase = tuple(phrase[phrase_start:1 + head - start])
                gram_counts[other_phrase] += 1
        else: 
            if len(phrase) < 3: 
                gram_counts[phrase] += 1
    return gram_counts
    
def get_significant_entities(truncate=True): 
    '''
    Gather tagged entity unigrams and bigrams
    that we would want to include in our analysis 
    '''
    conf = SparkConf()
    sc = SparkContext(conf=conf)
    sqlContext = SQLContext(sc)
    
    categories = get_sr_cats()
    df = load_gram_counts(categories, sqlContext)

    all_counts = df.rdd.map(lambda x: (x[0], x[1])).reduceByKey(lambda x,y: x + y).collectAsMap()
    all_counts = Counter(all_counts)
    u_total = df.rdd.filter(lambda x: len(x[0].split(' ')) == 1).map(lambda x: (1, x[1])).reduceByKey(lambda x,y: x + y).collect()[0][1]
    b_total = df.rdd.filter(lambda x: len(x[0].split(' ')) == 2).map(lambda x: (1, x[1])).reduceByKey(lambda x,y: x + y).collect()[0][1]
    
    sc.stop()

    # look at tagged entities 
    tokenizer = BasicTokenizer(do_lower_case=True)
    months = ['2011-01', '2011-03', '2006-01', '2011-07', '2008-11', '2008-02', '2012-09', '2014-07']
    gram_counts = Counter()
    for m in months: 
        with open(LOGS + 'deprel_reddit/' + m + '_deps.json', 'r') as infile: 
            deps = json.load(infile)
        with open(LOGS + 'deprel_reddit/' + m + '_depheads.json', 'r') as infile: 
            depheads = json.load(infile)
        with open(LOGS + 'tagged_people/' + m, 'r') as infile: 
            for i, line in enumerate(infile): 
                gram_counts = update_gram_counts(line, categories, tokenizer, \
                                                 deps, depheads, gram_counts, reddit=True)
    forums = ['love_shy']
    for f in forums: 
        with open(LOGS + 'deprel_forums/' + f + '_deps.json', 'r') as infile: 
            deps = json.load(infile)
        with open(LOGS + 'deprel_forums/' + f + '_depheads.json', 'r') as infile: 
            depheads = json.load(infile)
        with open(LOGS + 'tagged_people/' + f, 'r') as infile: 
            for i, line in enumerate(infile): 
                gram_counts = update_gram_counts(line, categories, tokenizer, \
                                                 deps, depheads, gram_counts, reddit=True)
    
    # save significant entities that occur at least X times 
    unigrams = Counter()
    bigrams = Counter()
    for gram in gram_counts: 
        if gram_counts[gram] < 10: continue
        if all_counts[' '.join(gram)] < 500: continue
        gram_len = len(gram)
        assert gram_len < 3 and gram_len > 0
        if gram_len == 1: 
            unigrams[gram[0]] = all_counts[' '.join(gram)]
        if gram_len == 2: 
            bigrams[' '.join(gram)] = all_counts[' '.join(gram)]
    for tup in unigrams.most_common(): 
        print("********UNIGRAM", tup[0], tup[1], all_counts[tup[0]]) # TODO: also write out the count of ner labels they use and their determiner or possessive counts  
    for tup in bigrams.most_common(): 
        print("--------BIIGRAM", tup[0], tup[1], all_counts[tup[0]])

def main(): 
    #count_glosswords_in_tags()
    #get_ngrams_glosswords()
    get_significant_entities()

if __name__ == '__main__':
    main()