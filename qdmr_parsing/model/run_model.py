
import argparse
import json
import os
import pandas as pd
import random

from evaluation.decomposition import Decomposition, get_decomposition_from_tokens
from model.rule_based.rule_based_model import RuleBasedModel
from model.rule_based.copy_model import CopyModel
from model.seq2seq.seq2seq_model import Seq2seqModel


pd.set_option('display.width', 1000)
pd.set_option('display.max_columns', 1000)


def init_model(args):
    if args.model == "copy":
        model = CopyModel()
    elif args.model == "rule_based":
        model = RuleBasedModel()
    else:
        model = Seq2seqModel(args.model_dir, args.model, args.model == "copynet",
                             args.cuda_device)

    return model


def main(args):
    # load data
    if args.input_file:
        with open(args.input_file, 'r', encoding='utf-8') as fd:
            lines = fd.readlines()
        if args.random_n and len(lines) > args.random_n:
            lines = random.sample(lines, args.random_n)

        lines_parts = [line.strip('\n').split('\t') for line in lines]
        questions = [line_parts[0] for line_parts in lines_parts]

        if args.model == "dynamic":
            allowed_tokens = [line_parts[1] for line_parts in lines_parts]
            golds_index = 2
        else:
            allowed_tokens = None
            golds_index = 1

        golds = [line_parts[golds_index].split('@@SEP@@') for line_parts in lines_parts]
        golds = [[s.strip() for s in g] for g in golds]

    else:
        questions = [args.question]
        if args.evaluate:
            golds = [[s.strip() for s in args.gold.split('@@SEP@@')]]
        allowed_tokens = None

    # initialize a model
    model = init_model(args)

    # load pre-computed predictions if provided, otherwise,
    # decompose questions using the model.
    if args.preds_file:
        decompositions = model.load_decompositions_from_file(args.preds_file)
    else:
        decompositions = model.predict(questions, args.print_non_decomposed, args.verbose,
                                       extra_args=allowed_tokens)

    # evaluation
    if args.evaluate:
        golds = [Decomposition(g) for g in golds]
        metadata = pd.read_csv(args.metadata_file) if args.metadata_file else None
        model.evaluate(questions, decompositions, golds, metadata,
                       output_path_base=args.output_file_base, num_processes=args.num_processes)


def validate_args(args):
    # input question(s) for decomposition are provided.
    assert not (args.input_file and args.question)
    assert not (args.random_n and not args.input_file)
    assert not (args.preds_file and not args.input_file)
    assert not (args.preds_file and args.random_n)

    # input files exist.
    if args.input_file:
        assert os.path.exists(args.input_file)
    if args.preds_file:
        assert os.path.exists(args.preds_file)

    # for evaluation of a given question, one must provide its gold decomposition.
    if args.evaluate and args.question:
        assert args.gold

    # seq2seq model options.
    if args.model in ["seq2seq", "copynet", "dynamic"]:
        assert os.path.exists(args.model_dir)

    # seq2seq dynamic only accepts input file at the moment
    # TODO: add option for single example prediction
    if args.model == "dynamic":
        assert args.input_file


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="preprocess examples\n"
                    "example: python model/run_model.py --input_file data/dev_dynamic.tsv --random_n 10 "
                    "--model dynamic --model_dir misc/seq2seq_dynamic_test/ --evaluate")
    parser.add_argument('--input_file', type=str, help='path to input file')
    parser.add_argument('--preds_file', type=str, help='path to predictions file generated by allennlp model')
    parser.add_argument('--random_n', type=int, default=0,
                        help='choose n random examples from input file')
    parser.add_argument('--question', type=str, help='question to decompose')
    parser.add_argument('--gold', type=str, help='for evaluation, gold decomposition of the given question')
    parser.add_argument('--model', type=str, choices=["rule_based", "copy", "seq2seq", "copynet", "dynamic"],
                        help='which model to run')

    parser.add_argument('--evaluate', action='store_true', default=False, help='evaluate decompositions')
    parser.add_argument('--num_processes', type=int, default=5,
                        help='number of processes for multiprocessing evaluation (used for GED+ only)')
    parser.add_argument('--cuda_device', type=int, default=-1,
                        help='cuda device to use for evaluation of seq2seq models')
    parser.add_argument('--metadata_file', type=str, default=None,
                        help='path to metadata file (csv file with examples before preprocessing)')
    parser.add_argument('--output_file_base', type=str, default=None, help='path to output file')

    # Rule based model options.
    parser.add_argument('--print_non_decomposed', action='store_true', default=False,
                        help='print non-decomposed questions')
    parser.add_argument('--verbose', action='store_true', default=False,
                        help='print intermediate decomposition steps')

    # Seq2seq model options.
    parser.add_argument('--model_dir', type=str, default=None, help='path to model base directory')

    args = parser.parse_args()

    validate_args(args)
    main(args)
