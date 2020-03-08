'''This code is mostly taken from https://github.com/shmsw25/DecompRC/tree/master/DecompRC.'''

import os
import json
import collections
import math
import six
from tqdm import tqdm
import numpy as np
import tokenization
from collections import defaultdict

rawResult = collections.namedtuple("RawResult", ["unique_id", "start_logits", "end_logits"])


def get_predictions(logger, all_examples, all_features, all_results, n_best_size,
                     max_answer_length, do_lower_case, verbose_logging):

    """Return the final predictions."""

    example_index_to_features = collections.defaultdict(list)
    for feature in all_features:
        example_index_to_features[feature.example_index].append(feature)

    unique_id_to_result = {}
    for result in all_results:
        unique_id_to_result[result.unique_id] = result

    _PrelimPrediction = collections.namedtuple(  
       "PrelimPrediction",
       ["feature_index", "start_index", "end_index", "logit", "no_answer_logit"])

    all_predictions = collections.OrderedDict()
    all_nbest_json = collections.OrderedDict()

    for example_index, example in enumerate(all_examples):
        features = example_index_to_features[example_index]
        prelim_predictions = []
        yn_predictions = []

        results = sorted(enumerate(features), key=lambda f: unique_id_to_result[f[1].unique_id].switch[3])[:1]
        #results = enumerate(features)
        for (feature_index, feature) in results:
            result = unique_id_to_result[feature.unique_id]
            switch = np.argmax(result.switch[:3])
            if switch > 0:
                prelim_predictions.append(
                        _PrelimPrediction(
                            feature_index=feature_index,
                            start_index=-switch,
                            end_index=-switch,
                            logit=result.switch[switch]-result.switch[3],
                            no_answer_logit=result.switch[3]))
                continue

            scores = []
            start_logits = result.start_logits[:len(feature.tokens)]
            end_logits = result.end_logits[:len(feature.tokens)]
            for (i, s) in enumerate(start_logits):
                for (j, e) in enumerate(end_logits[i:i+10]):
                    scores.append(((i, i+j), s+e-result.switch[3]))

            scores = sorted(scores, key=lambda x: x[1], reverse=True)
            for (start_index, end_index), score in scores:
                if start_index >= len(feature.tokens):
                    continue
                if end_index >= len(feature.tokens):
                    continue
                if start_index not in feature.token_to_orig_map:
                    continue
                if end_index not in feature.token_to_orig_map:
                    continue
                if not feature.token_is_max_context.get(start_index, False):
                    continue
                if end_index < start_index:
                    continue
                length = end_index - start_index + 1
                if length > max_answer_length:
                    continue
                prelim_predictions.append(
                   _PrelimPrediction(
                       feature_index=feature_index,
                       start_index=start_index,
                       end_index=end_index,
                       logit=score, no_answer_logit=result.switch[3]))

        prelim_predictions = sorted(
                prelim_predictions,
                key=lambda x: x.logit,
                reverse=True)

        _NbestPrediction = collections.namedtuple(  
           "NbestPrediction", ["text", "logit", "no_answer_logit", "evidence"])

        seen_predictions = {}
        nbest = []
        for pred in prelim_predictions:
            if len(nbest) >= n_best_size:
                break
            feature = features[pred.feature_index]

            #if pred.logit < 0:
            #    final_text = '<NULL>'
            #el
            if pred.start_index == pred.end_index == -1:
                final_text = "yes"
                sp_fact = " ".join(feature.doc_tokens)
            elif pred.start_index == pred.end_index == -2:
                final_text = "no"
                sp_fact = " ".join(feature.doc_tokens)
            else:
                tok_tokens = feature.tokens[pred.start_index:(pred.end_index + 1)]
                orig_doc_start = feature.token_to_orig_map[pred.start_index]
                orig_doc_end = feature.token_to_orig_map[pred.end_index]
                orig_tokens = feature.doc_tokens[orig_doc_start:(orig_doc_end + 1)]
                tok_text = " ".join(tok_tokens)

                # De-tokenize WordPieces that have been split off.
                tok_text = tok_text.replace(" ##", "")
                tok_text = tok_text.replace("##", "")

                # Clean whitespace
                tok_text = tok_text.strip()
                tok_text = " ".join(tok_text.split())
                orig_text = " ".join(orig_tokens)

                final_text = get_final_text(tok_text, orig_text, do_lower_case, \
                                            logger, verbose_logging)
                sp_fact = " ".join(feature.doc_tokens[:orig_doc_start] + ["@@"] + \
                                   orig_tokens + ["@@"] + feature.doc_tokens[orig_doc_end+1:])

            if final_text in seen_predictions:
                continue

            nbest.append(
               _NbestPrediction(
                   text=final_text,
                   logit=pred.logit,
                    no_answer_logit=pred.no_answer_logit,
                    evidence=sp_fact))

        # In very rare edge cases we could have no valid predictions. So we
        # just create a nonce prediction in this case to avoid failure.
        if not nbest:
            nbest.append(
               _NbestPrediction(text="NULL", logit=0.0, no_answer_logit=10000, evidence="empty"))

        assert len(nbest) >= 1

        total_scores = []
        for entry in nbest:
            total_scores.append(entry.logit)

        probs = _compute_softmax(total_scores)
        nbest_json = []
        for (i, entry) in enumerate(nbest):
            output = collections.OrderedDict()
            output['text'] = entry.text
            output['probability'] = probs[i]
            output['logit'] = entry.logit
            output['no_answer_logit'] = entry.no_answer_logit
            output['evidence'] = entry.evidence
            nbest_json.append(output)

        assert len(nbest_json) >= 1

        all_predictions[example.qas_id] = (nbest_json[0]["text"], example.all_answers)
        all_nbest_json[example.qas_id] = nbest_json

    return all_predictions, all_nbest_json


def get_final_text(pred_text, orig_text, do_lower_case, logger, verbose_logging):
    """Project the tokenized prediction back to the original text."""
    def _strip_spaces(text):
        ns_chars = []
        ns_to_s_map = collections.OrderedDict()
        for (i, c) in enumerate(text):
            if c == " ":
                continue
            ns_to_s_map[len(ns_chars)] = i
            ns_chars.append(c)
        ns_text = "".join(ns_chars)
        return (ns_text, ns_to_s_map)

    # We first tokenize `orig_text`, strip whitespace from the result
    # and `pred_text`, and check if they are the same length. If they are
    # NOT the same length, the heuristic has failed. If they are the same
    # length, we assume the characters are one-to-one aligned.
    tokenizer = tokenization.BasicTokenizer(do_lower_case=do_lower_case)

    tok_text = " ".join(tokenizer.tokenize(orig_text))

    start_position = tok_text.find(pred_text)
    if start_position == -1:
        if verbose_logging:
            logger.info(
                "Unable to find text: '%s' in '%s'" % (pred_text, orig_text))
        return orig_text
    end_position = start_position + len(pred_text) - 1

    (orig_ns_text, orig_ns_to_s_map) = _strip_spaces(orig_text)
    (tok_ns_text, tok_ns_to_s_map) = _strip_spaces(tok_text)

    if len(orig_ns_text) != len(tok_ns_text):
        if verbose_logging:
            logger.info("Length not equal after stripping spaces: '%s' vs '%s'",
                            orig_ns_text, tok_ns_text)
        return orig_text

    # We then project the characters in `pred_text` back to `orig_text` using
    # the character-to-character alignment.
    tok_s_to_ns_map = {}
    for (i, tok_index) in six.iteritems(tok_ns_to_s_map):
        tok_s_to_ns_map[tok_index] = i

    orig_start_position = None
    if start_position in tok_s_to_ns_map:
        ns_start_position = tok_s_to_ns_map[start_position]
        if ns_start_position in orig_ns_to_s_map:
            orig_start_position = orig_ns_to_s_map[ns_start_position]

    if orig_start_position is None:
        if verbose_logging:
            logger.info("Couldn't map start position")
        return orig_text

    orig_end_position = None
    if end_position in tok_s_to_ns_map:
        ns_end_position = tok_s_to_ns_map[end_position]
        if ns_end_position in orig_ns_to_s_map:
            orig_end_position = orig_ns_to_s_map[ns_end_position]

    if orig_end_position is None:
        if verbose_logging:
            logger.info("Couldn't map end position")
        return orig_text

    output_text = orig_text[orig_start_position:(orig_end_position + 1)]
    return output_text


def _compute_softmax(scores):
    """Compute softmax probability over raw logits."""
    if not scores:
        return []

    max_score = None
    for score in scores:
        if max_score is None or score > max_score:
            max_score = score

    exp_scores = []
    total_sum = 0.0
    for score in scores:
        x = math.exp(score - max_score)
        exp_scores.append(x)
        total_sum += x

    probs = []
    for score in exp_scores:
        probs.append(score / total_sum)
    return probs
