# Policy retrieval eval

| Strategy | recall@2 | MRR |
|---|---|---|
| bm25 | 79.2% | 0.769 |
| embeddings | 91.7% | 0.899 |
| hybrid | 83.3% | 0.792 |

## Misses (top-2)

### bm25

- `return-defect`: "a guitarra chegou com o captador chiando, quero trocar" expected ['4.2'], top ['4', '4.3', '1']
- `delivery-dourados`: "demora quanto pra chegar em Dourados?" expected ['5.2'], top ['1', '1.1', '1.2']
- `delivery-tracking`: "cade meu pedido?? como acompanho a entrega" expected ['5.3'], top ['5.1', '8.2', '9']
- `scope-accessories`: "vcs vendem corda de violao e palheta?" expected ['7.1'], top ['8.3', '1', '7.1']
- `special-out-of-stock`: "o baixo que eu quero ta esgotado, quando volta?" expected ['7.3'], top ['6.2', '6.1', '1']

### embeddings

- `return-non-eligible`: "comprei um produto da promoção de saldão, ele pode ser trocado?" expected ['4.4'], top ['4.3', '4.2', '4.1']
- `scope-accessories`: "vcs vendem corda de violao e palheta?" expected ['7.1'], top ['1', '8.3', '7.1']

### hybrid

- `return-non-eligible`: "comprei um produto da promoção de saldão, ele pode ser trocado?" expected ['4.4'], top ['4.2', '4.3', '4.4']
- `delivery-dourados`: "demora quanto pra chegar em Dourados?" expected ['5.2'], top ['1', '2', '4.1']
- `scope-accessories`: "vcs vendem corda de violao e palheta?" expected ['7.1'], top ['8.3', '1', '7.1']
- `special-out-of-stock`: "o baixo que eu quero ta esgotado, quando volta?" expected ['7.3'], top ['1', '4.2', '6.2']

## Decision

switch to embeddings: recall@2 91.7% vs BM25 79.2%
