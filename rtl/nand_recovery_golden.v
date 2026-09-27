// NAND read-recovery controller + NAND error model (virtual IP) -- GOLDEN (spec) version.
// Bit-exact with nand_dut.py (buggy=False); tables and constants from spec/nand_recovery.json.
//
// Mapping update protocol (spec): relocation targets are first RESERVED in one of two
// slots and written to the logical-to-physical map on COMMIT. A failed relocation program
// cancels its reservation. After a verify-read failure is recovered, the rewrite target
// overwrites the most recent reservation. Every commit must write exactly one map entry.
//
// Transaction level: the FSM moves only on an accepted transaction (in_valid && in_ready).
// in_ready drops for BUSY_CYCLES after READ/REMAP (NAND R/B# busy). The busy length
// changes timing only, never the result, because the error-model LFSR also advances
// once per accepted transaction, not per clock.
module nand_recovery #(
    parameter integer BUSY_CYCLES = 3
) (
    input  wire        clk,
    input  wire        por_n,        // power-on reset (async, constant reset values)
    input  wire        rst_n,        // host reset: clears the controller only
    input  wire        seed_we,      // synchronous load of the error-model seed
    input  wire [15:0] lfsr_seed,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [5:0]  in_tx,        // {opcode[1:0], param[3:0]}
    output reg  [3:0]  state_o,
    output reg  [3:0]  hint_o,
    output reg         err_o,        // 1-cycle pulse: unexpected command during recovery
    output reg         map_commit_o, // 1-cycle pulse: the map was updated
    output reg  [1:0]  map_wr_cnt_o  // map entries written by that commit (spec: exactly 1)
);
    localparam [3:0] IDLE = 4'd0, ECC_FAIL = 4'd1, RECOVERED = 4'd2, PGM_FAIL = 4'd3,
                     RELOCATED = 4'd4, ECC_FAIL2 = 4'd5, RECOVERED2 = 4'd6,
                     MAP_PENDING = 4'd7;
    localparam [1:0] OP_STATUS = 2'd0, OP_READ = 2'd1, OP_RETRY = 2'd2, OP_REMAP = 2'd3;
    localparam [3:0] WEAK_PAGE = 4'd10, SPARE_BLK = 4'd3, VERIFY_PAGE = 4'd5, COMMIT = 4'd15;

    // NAND characterization data: which retry voltage level recovers a given error hint
    function [3:0] retry_table(input [3:0] h);
        case (h)
            4'd0: retry_table = 4'd7;   4'd1: retry_table = 4'd12;  4'd2: retry_table = 4'd3;
            4'd3: retry_table = 4'd14;  4'd4: retry_table = 4'd0;   4'd5: retry_table = 4'd9;
            4'd6: retry_table = 4'd5;   4'd7: retry_table = 4'd11;  4'd8: retry_table = 4'd2;
            4'd9: retry_table = 4'd15;  4'd10: retry_table = 4'd8;  4'd11: retry_table = 4'd1;
            4'd12: retry_table = 4'd13; 4'd13: retry_table = 4'd6;  4'd14: retry_table = 4'd10;
            default: retry_table = 4'd4;
        endcase
    endfunction

    // spare block to use for a given program-failure hint (failing plane)
    function [3:0] spare_table(input [3:0] h);
        case (h)
            4'd0: spare_table = 4'd9;   4'd1: spare_table = 4'd2;   4'd2: spare_table = 4'd14;
            4'd3: spare_table = 4'd5;   4'd4: spare_table = 4'd11;  4'd5: spare_table = 4'd0;
            4'd6: spare_table = 4'd7;   4'd7: spare_table = 4'd12;  4'd8: spare_table = 4'd4;
            4'd9: spare_table = 4'd15;  4'd10: spare_table = 4'd1;  4'd11: spare_table = 4'd8;
            4'd12: spare_table = 4'd3;  4'd13: spare_table = 4'd13; 4'd14: spare_table = 4'd6;
            default: spare_table = 4'd10;
        endcase
    endfunction

    // Error model: 16-bit Fibonacci LFSR, advanced 7 steps per accepted transaction so
    // that consecutive NAND operations draw disjoint bits (independent failures).
    // 7 is coprime with the period 65535, so the full sequence is still used.
    localparam integer LEAP = 7;
    function [15:0] lfsr_adv(input [15:0] x);
        integer i;
        reg [15:0] y;
        begin
            y = x;
            for (i = 0; i < LEAP; i = i + 1)
                y = {y[0] ^ y[2] ^ y[3] ^ y[5], y[15:1]};
            lfsr_adv = y;
        end
    endfunction

    reg  [15:0] lfsr;
    reg  [7:0]  busy;
    wire [15:0] lfsr_nx  = lfsr_adv(lfsr);
    wire        fail     = lfsr_nx[0];
    wire [3:0]  rnd_hint = lfsr_nx[4:1];
    wire [1:0]  op       = in_tx[5:4];
    wire [3:0]  prm      = in_tx[3:0];
    wire        accept   = in_valid && in_ready;

    // Map reservations: two slots, filled in order by rsv_idx
    reg  [1:0]  pend_v;
    reg  [3:0]  pend_blk0, pend_blk1;
    reg  [1:0]  rsv_idx;
    wire [1:0]  rsv_last   = rsv_idx - 2'd1;      // index of the most recent reservation
    wire        rearm_slot = rsv_last[0];     // overwrite the most recent reservation

    assign in_ready = (busy == 8'd0);

    reg [3:0] ns, nh;
    reg       ne, rsv, cancel, rearm, commit;
    reg [3:0] rsv_blk;
    always @(*) begin
        ns = IDLE;  // any unexpected transaction aborts to IDLE
        nh = 4'd0;
        ne = (state_o != IDLE);  // ...and during recovery that abort is reported on err_o
        rsv = 1'b0; cancel = 1'b0; rearm = 1'b0; commit = 1'b0; rsv_blk = 4'd0;
        case (state_o)
            IDLE:        if (op == OP_READ   && prm == WEAK_PAGE)
                             begin ns = fail ? ECC_FAIL  : IDLE; nh = fail ? rnd_hint : 4'd0; end
            ECC_FAIL:    if (op == OP_RETRY  && prm == retry_table(hint_o))
                             begin ns = RECOVERED; ne = 1'b0; end
            RECOVERED:   if (op == OP_REMAP  && prm == SPARE_BLK) begin
                             ns = fail ? PGM_FAIL : IDLE; nh = fail ? rnd_hint : 4'd0; ne = 1'b0;
                             rsv = 1'b1; rsv_blk = SPARE_BLK;
                             cancel = fail;       // program failed: drop this reservation
                             commit = ~fail;      // program passed: write it to the map
                         end
            PGM_FAIL:    if (op == OP_REMAP  && prm == spare_table(hint_o))
                             begin ns = RELOCATED; ne = 1'b0; rsv = 1'b1; rsv_blk = prm; end
            RELOCATED:   if (op == OP_READ   && prm == VERIFY_PAGE) begin
                             ns = fail ? ECC_FAIL2 : IDLE; nh = fail ? rnd_hint : 4'd0; ne = 1'b0;
                             commit = ~fail;      // verify passed: write the reservation
                         end
            ECC_FAIL2:   if (op == OP_RETRY  && prm == retry_table(hint_o))
                             begin ns = RECOVERED2; ne = 1'b0; end
            RECOVERED2:  if (op == OP_STATUS && prm == 4'd0)
                             begin ns = MAP_PENDING; ne = 1'b0; rearm = 1'b1; end  // rewrite target
            MAP_PENDING: if (op == OP_REMAP  && prm == COMMIT)
                             begin ns = IDLE; ne = 1'b0; commit = 1'b1; end
            default:     ns = IDLE;
        endcase
    end

    // entries written by a commit: every valid reservation, plus one made in this cycle
    wire [1:0] commit_cnt = {1'b0, pend_v[0]} + {1'b0, pend_v[1]} + {1'b0, rsv & ~cancel};

    always @(posedge clk or negedge por_n) begin
        if (!por_n) begin
            lfsr    <= 16'hACE1;
            state_o <= IDLE;  hint_o <= 4'd0;  busy <= 8'd0;  err_o <= 1'b0;
            map_commit_o <= 1'b0;  map_wr_cnt_o <= 2'd0;
            pend_v  <= 2'b00; pend_blk0 <= 4'd0; pend_blk1 <= 4'd0; rsv_idx <= 2'd0;
        end else if (seed_we) begin  // an all-zero seed would lock the LFSR
            lfsr    <= (lfsr_seed == 16'd0) ? 16'hACE1 : lfsr_seed;
            err_o   <= 1'b0;  map_commit_o <= 1'b0;  map_wr_cnt_o <= 2'd0;
        end else if (!rst_n) begin  // host reset leaves the NAND error model running
            state_o <= IDLE;  hint_o <= 4'd0;  busy <= 8'd0;  err_o <= 1'b0;
            map_commit_o <= 1'b0;  map_wr_cnt_o <= 2'd0;
            pend_v  <= 2'b00; rsv_idx <= 2'd0;
        end else if (accept) begin
            lfsr    <= lfsr_nx;
            state_o <= ns;
            hint_o  <= nh;
            err_o   <= ne;
            busy    <= (op == OP_READ || op == OP_REMAP) ? BUSY_CYCLES[7:0] : 8'd0;
            map_commit_o <= commit;
            map_wr_cnt_o <= commit ? commit_cnt : 2'd0;
            if (ns == IDLE) begin               // flow finished or aborted: drop reservations
                pend_v  <= 2'b00;
                rsv_idx <= 2'd0;
            end else begin
                if (rsv) begin
                    if (rsv_idx[0]) begin pend_v[1] <= ~cancel; pend_blk1 <= rsv_blk; end
                    else            begin pend_v[0] <= ~cancel; pend_blk0 <= rsv_blk; end
                    rsv_idx <= rsv_idx + 2'd1;
                end
                if (rearm) begin
                    if (rearm_slot) begin pend_v[1] <= 1'b1; pend_blk1 <= pend_blk1 + 4'd1; end
                    else            begin pend_v[0] <= 1'b1; pend_blk0 <= pend_blk1 + 4'd1; end
                end
            end
        end else begin
            err_o <= 1'b0;  map_commit_o <= 1'b0;  map_wr_cnt_o <= 2'd0;
            if (busy != 8'd0) busy <= busy - 8'd1;
        end
    end
endmodule
