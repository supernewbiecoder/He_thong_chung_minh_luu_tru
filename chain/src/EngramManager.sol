// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

import {IEngramVerifier} from "./interfaces/IEngramVerifier.sol";
import {IBlobstream} from "./interfaces/IBlobstream.sol";

/*═══════════════════════════════════════════════════════════════════════════
  EngramManager — bề mặt on-chain của Engram

  [SPEC §C.1]  Tầng L4 trong kiến trúc bốn tầng
  [SPEC §D.2]  Public values 297 byte
  [SPEC §I.1]  Kinh tế và quyết toán

  ── ĐIỀU DUY NHẤT CẦN NHỚ VỀ HỢP ĐỒNG NÀY ─────────────────────────────────

  Nó KHÔNG bao giờ nhìn thấy một bằng chứng lưu trữ nào. Nó chỉ thấy MỘT bằng
  chứng Groth16 356 byte và 297 byte public values, mỗi epoch một lần, bất kể
  mạng có 10 hay 10.000 hợp đồng.

  Đó là toàn bộ đóng góp của Engram. Chi phí đo được: 474.260 gas, biến động
  0,0025 % qua bốn bậc độ lớn của N. Đường cơ sở "một bản ghi mỗi nút" chết ở
  727 nút.

  ── BA THỨ HỢP ĐỒNG KHÔNG LÀM ─────────────────────────────────────────────

  1. KHÔNG tự phân phối tiền. Mỗi lần chuyển ETH tốn ~14.000 gas; trả cho 1.164
     nút là vượt trần giao dịch. Dùng cơ chế KÉO: ai muốn tiền thì tự nộp lá
     cùng đường Merkle. [SPEC §I.1.1]

  2. KHÔNG nhận bundle. Bundle đi lên Celestia, không lên đây. Cả đời một hợp
     đồng, nút chỉ gửi ba giao dịch: registerSealed, activate, claimSettlement.

  3. KHÔNG cưỡng chế được việc các mảnh có piece_root khác nhau. Đó là yêu cầu
     phía khách, giao thức không kiểm được. [SPEC §J.1.4]
═══════════════════════════════════════════════════════════════════════════*/

contract EngramManager {
    /*═══════════════════════════════════════════════════════════════════════
      1. HẰNG SỐ GHIM  ·  [SPEC §D.2.2]

      Đây là chỗ CẢ HỆ TREO LÊN. Nếu storage_vk_digest chỉ nằm trong public
      values mà KHÔNG so với hằng số ghim ở đây, thì host tự sinh một khoá xác
      minh yếu, đưa vào guest, guest tính đúng digest của khoá yếu đó, và mọi
      thứ khớp. Bằng chứng "hợp lệ" cho một hệ chứng minh mà host giữ cửa sau.

      ── GIỚI HẠN PHẢI ĐỌC TRƯỚC KHI TIN VÀO PHÉP GHIM NÀY  [SPEC §K.2.1 ①] ──

      Spartan trên HyperKZG cần một SRS. Nếu SRS sinh tại chỗ thì người sinh
      giữ trapdoor, và giữ trapdoor nghĩa là GIẢ ĐƯỢC BẰNG CHỨNG.

      Nên cho tới khi SRS đến từ một ceremony công khai, phép ghim dưới đây
      CHƯA CÓ HIỆU LỰC AN TOÀN: nó ghim một khoá mà người sinh có thể có cửa
      sau. Đừng liệt kê nó như một cơ chế đang hoạt động.

      Đây là giới hạn nghiêm trọng nhất còn lại của hệ thống.
    ═══════════════════════════════════════════════════════════════════════*/

    bytes32 public immutable STORAGE_VK_DIGEST;
    bytes32 public immutable ACTIVATION_VK_DIGEST;
    /// [T3.5] KHÔNG được đọc ở đâu trong hợp đồng, và điều đó là ĐÚNG: hợp đồng
    /// chỉ verify bằng chứng của aggregator, còn ChildProof của worker được
    /// aggregator guest verify đệ quy. Hằng số này tồn tại để **ghim** khoá đó
    /// ở một nơi bất biến, công khai, để guest lấy làm hằng số biên dịch. Nếu
    /// guest không ghim nó thì mắt xích worker → aggregator không có neo, và
    /// hiện điều đó là một GIẢ ĐỊNH về chương trình chứ không phải phép kiểm
    /// của hợp đồng.
    /// [R5] Neo dự phòng cho `_activationBeacon` trước khi có epoch đầu tiên.
    bytes32 public immutable genesisAnchor;

    bytes32 public immutable WORKER_PROGRAM_VKEY;
    bytes32 public immutable AGGREGATOR_PROGRAM_VKEY;
    /// [R12] Public values KHÔNG có trường version nên hằng số này không đối
    /// chiếu được với bất cứ thứ gì. Giữ lại để đánh dấu phiên bản bố cục dữ
    /// liệu ngoài chuỗi (namespace kind, tiêu đề blob), và ghi rõ ở đây rằng nó
    /// KHÔNG phải một phép kiểm on-chain.
    uint8 public constant PROTOCOL_VERSION = 1;

    IEngramVerifier public immutable verifier;
    IBlobstream public immutable blobstream;

    /*═══════════════════════════════════════════════════════════════════════
      2. THAM SỐ KINH TẾ  ·  [SPEC §K.1]
    ═══════════════════════════════════════════════════════════════════════*/

    /// [CHỐT B2-a] [SPEC §J.2.5] Ngưỡng cọc mỗi khe.
    /// Không có nó, nút đặt 1 ETH rồi nhận bao nhiêu hợp đồng cũng được; tới
    /// ~10.000 hợp đồng thì cọc mỗi hợp đồng tụt dưới ngưỡng và gian lận có lãi.
    uint256 public constant MIN_COLLATERAL_PER_SLOT = 1e14; // 0,0001 ETH

    /// [SPEC §I.1.2] Hoa hồng cho người nộp lá phạt hộ.
    /// NGHỊCH LÝ CÓ LỢI: gian lận càng nặng, hoa hồng càng lớn, càng chắc có
    /// người săn. Lá thưởng thì nút tự lo; lá phạt thì không ai muốn nộp.
    uint16 public constant BOUNTY_BPS = 500; // 5 %

    /// [SPEC §H.1.7] Ngưỡng nghẽn DA. `window_saturation` do guest tính từ kích
    /// thước square của block Celestia, thang [0,255].
    ///
    /// VÌ SAO CÓ NGƯỠNG NÀY. Hoa hồng ở trên giả định lá phạt phản ánh gian lận
    /// thật. Dưới nghẽn DA thì không: nút trung thực không đăng được bằng chứng
    /// và bị phạt hàng loạt, nên kẻ gây nghẽn tự nộp lá phạt và THU hoa hồng.
    /// Khoản thu đó tăng theo N, nên bất đẳng thức "chi phí tấn công > giá trị
    /// thu được" hỏng đúng lúc mạng lớn lên.
    ///
    /// Cách vá là cắt phần THU, không phải hạ mức phạt — mức phạt còn phải chặn
    /// nút xoá dữ liệu, và hoa hồng là TỈ LỆ của nó nên hạ phạt không đổi hình
    /// dạng bài toán. Epoch vượt ngưỡng: vẫn ghi FAIL, vẫn trừ, nhưng KHÔNG trả
    /// hoa hồng, nên gây nghẽn trở lại thành phá hoại thuần, không có lợi nhuận.
    uint8 public constant WINDOW_SATURATION_THRESHOLD = 179; // ~70 %

    uint16 public constant PROTOCOL_FEE_BPS = 200; // 2 %  [SPEC §I.1.5]

    /// [SPEC UC-02 A3] Hạn nút phải đăng ký sealed_root sau openDeal.
    ///
    /// [T2.4] Đổi đơn vị từ DEADLINE sang EPOCH. Lý do: hợp đồng không nhìn thấy
    /// chiều cao Celestia nên không biết deadline nào đang mở, và bản trước giải
    /// quyết điều đó bằng cách HỎI NGƯỜI GỌI. Epoch thì hợp đồng tự biết qua
    /// `lastCommittedEpoch`, nên không ai tự khai được.
    uint8 public constant ABORT_AFTER_EPOCHS = 1;

    /// [SPEC §K.1] Cọc khoá thêm sau khi xin rút.
    uint8 public constant COLLATERAL_LOCK_EPOCHS = 2;

    /// [T2.2 + T2.3] Hạn chót cam kết một epoch, đếm bằng block EVM.
    ///
    /// VÌ SAO CẦN. Bốn mắt xích bảo đảm rằng NẾU có epoch được cam kết thì nội
    /// dung đúng và đủ. Chúng không nói gì về việc CÓ epoch nào được cam kết hay
    /// không. Aggregator im lặng thì nút đã tốn ổ cứng cả ngày, worker đã tốn
    /// hàng trăm giờ CPU, không ai được trả, và KHÔNG AI BỊ PHẠT.
    ///
    /// Trong ngôn ngữ authenticated data structures, tính chất còn thiếu là
    /// FRESHNESS: câu trả lời phải đúng, đủ, VÀ mới.
    ///
    /// Dùng block EVM chứ không dùng chiều cao Celestia, vì đây là hạn chót về
    /// phía EVM và hợp đồng không nhìn thấy Celestia.
    uint64 public constant COMMIT_PERIOD_BLOCKS = 14_400; // ~48 giờ ở 12 s/block

    /// Ân hạn sau hạn chót trước khi cho phép huỷ epoch.
    uint64 public constant VOID_GRACE_BLOCKS = 1_200; // ~4 giờ

    /// Phần cọc aggregator bị cắt mỗi lần để lỡ hạn.
    uint16 public constant AGG_TIMEOUT_SLASH_BPS = 1_000; // 10 %

    /// Cọc tối thiểu để đăng ký làm aggregator.
    uint256 public constant MIN_AGG_COLLATERAL = 1 ether;

    /*═══════════════════════════════════════════════════════════════════════
      3. KIỂU DỮ LIỆU  ·  [SPEC §D.1]
    ═══════════════════════════════════════════════════════════════════════*/

    enum DealState {
        None,
        Pending,   // openDeal xong, chưa niêm phong
        Active,    // bằng chứng kích hoạt đã qua
        Closed,
        Aborted
    }

    enum EpochState {
        Open,
        Committed, // gốc trạng thái đã tiến, CHƯA rút được tiền
        Final,     // Blobstream đã chứng thực, claimSettlement mở
        Void       // cầu dao: không thưởng, không phạt, ký quỹ không tiêu
    }

    struct StorageProvider {
        /// [SPEC §D.1.2]
        bytes20 celestiaAddress;
        /// ↑ [CHỐT §J.2.1] NEO CHỐNG MẠO DANH BLOB.
        ///
        /// Cặp nhãn (provider_id, deal_id) là CÔNG KHAI, và namespace Celestia
        /// KHÔNG CÓ CHỦ. Nên kẻ ngoài đăng được blob mang đúng nhãn của nút P
        /// với giá 0,00009 $. Nếu worker lấy trúng blob rác thì P bị phạt oan.
        ///
        /// Cách chặn: share Celestia phiên bản 1 chứa trường signer 20 byte, và
        /// ĐỒNG THUẬN CELESTIA TỰ KIỂM nó trùng người ký giao dịch. Kẻ ngoài
        /// không điền giả được. Worker lọc bằng một phép so sánh 20 byte.
        ///
        /// Đăng ký PHẢI kèm chữ ký thách thức chứng minh nắm khoá Celestia —
        /// nếu không, kẻ tấn công đăng ký địa chỉ của người khác thành của mình.
        uint256 collateralWei;
        uint64 capacitySlots;
        uint64 usedSlots;
        uint64 withdrawRequestedAtEpoch;
        /// [R2] Treo khi cọc tụt dưới mức cần cho số khe đang dùng.
        bool suspended;
        /// [R3] Đổi địa chỉ Celestia phải chờ, xem `requestCelestiaAddressChange`.
        bytes20 pendingCelestiaAddress;
        uint64 celestiaChangeEffectiveEpoch;
        uint64 registeredAtEpoch;
        bytes32 providerRoot; // [SPEC §D.1.2] cây khe thưa cố định
        string multiaddr;     // [SPEC §D.1.3] NÊN là DNS, không phải IP thô
    }

    struct StorageDeal {
        address customer;
        address provider;
        bytes32 pieceRoot;    // giá trị DUY NHẤT trong hệ mà nút không tạo ra
        bytes32 sealedRoot;   // 0 khi còn Pending
        bytes32 activationBeacon;
        uint64 pieceSizeReal; // chunk THẬT, không tính đệm
        uint32 slotIdx;
        uint8 deadlineIdx;    // 0..D-1, cố định cả đời
        uint32 shard;         // H(deal_id) mod S_ns
        uint256 pricePerEpochWei;
        uint256 escrowWei;
        uint256 sealingFeeWei;      // [CHỐT B1-a]
        bool sealingFeeReleased;
        uint64 startEpoch;
        uint64 endEpoch;
        uint64 openedAtEpoch;
        DealState state;
    }

    struct EpochRecord {
        EpochState state;
        bytes32 batchRoot;
        bytes32 resultsRoot;
        /// data_root của block Celestia chứa danh sách quyết toán đầy đủ.
        /// `finalizeEpoch` đối chiếu nó với tuple Blobstream — xem ghi chú ở đó.
        bytes32 resultsDataRoot;
        bytes32 daCommitment;
        uint64 daNonce;
        bytes32 newStateRoot;
        uint32 numVerified;
        address submitter;
        /// [SPEC §H.1.7] Chung khe lưu với state+numVerified+submitter
        /// (1+4+20+1 = 26 byte < 32), nên trường này KHÔNG tốn thêm SSTORE nào.
        uint8 windowSaturation;
    }

    /*═══════════════════════════════════════════════════════════════════════
      4. TRẠNG THÁI
    ═══════════════════════════════════════════════════════════════════════*/

    mapping(address => StorageProvider) public providers;
    mapping(uint64 => EpochRecord) public epochs;

    /// `internal` chứ KHÔNG `public`, và có getter viết tay ở dưới.
    ///
    /// ── VÌ SAO ──────────────────────────────────────────────────────────
    ///
    /// `StorageDeal` có 17 trường. Getter mà Solidity TỰ SINH cho một mapping
    /// public phải trả về đủ 17 giá trị rời, mà EVM chỉ truy cập được 16 khe
    /// trên stack. Kết quả: "Stack too deep" — và lỗi đó KHÔNG chỉ vào dòng
    /// nào trong mã, vì hàm gây ra nó không do người viết.
    ///
    /// Dấu hiệu nhận biết: rỗng hoá TẤT CẢ thân hàm mà vẫn tràn.
    ///
    /// Getter viết tay trả về cả struct trong bộ nhớ — một khe stack duy nhất,
    /// và chỗ gọi đọc theo TÊN trường thay vì theo thứ tự, nên thêm bớt trường
    /// sau này không âm thầm làm hỏng bên gọi.
    mapping(bytes32 => StorageDeal) internal _deals;

    function deals(bytes32 dealId) external view returns (StorageDeal memory) {
        return _deals[dealId];
    }

    /// Chống rút hai lần. [SPEC §I.1.1]
    mapping(bytes32 => bool) public settlementClaimed;

    /// [SPEC §I.1.2 ④] Khai tuần tự: muốn nhận thưởng epoch E phải đã khai mọi
    /// epoch trước. Chỉ MỘT biến mỗi nút, không đụng guest.
    mapping(address => uint64) public lastClaimedEpoch;

    bytes32 public currentStateRoot;
    uint64 public lastCommittedEpoch;

    // ── AGGREGATOR: đăng ký, chỉ định, phạt  [T2.3 phương án B] ──────────
    struct AggregatorInfo {
        uint256 collateralWei;
        bool registered;
        uint64 timeouts;
        /// [R6] Epoch lúc xin rút. 0 nghĩa là chưa xin.
        uint64 withdrawRequestedAtEpoch;
    }

    /// [T1.3] Nonce mỗi khách, để `dealId` không mài được.
    mapping(address => uint256) public dealNonce;

    /// [T1.3] Số deadline mỗi epoch và số mảnh. Hợp đồng cần chúng để dẫn xuất
    /// vị trí hợp đồng, và guest cũng dùng cùng bộ giá trị này.
    /// [R7] Đặt trong constructor, KHÔNG ghim cứng.
    ///
    /// Bản trước ghim `DEADLINES_PER_EPOCH = 48` và `shardCount = 10`, tức ghim
    /// hồ sơ production. Chạy với `PROFILE_SIM` (D = 4) thì `deadlineIdx` mà hợp
    /// đồng dẫn xuất nằm trong [0,48) còn guest chỉ xét [0,4), nên phần lớn hợp
    /// đồng rơi vào deadline không ô nào phủ. Chưa lộ ra vì luồng Python không
    /// gọi `openDeal` của Solidity, nhưng nối thật là vỡ ngay.
    ///
    /// `shardCount` bản trước còn là biến `public` KHÔNG CÓ SETTER: vừa tốn
    /// SLOAD vừa làm người đọc tưởng đổi được.
    uint64 public immutable DEADLINES_PER_EPOCH;
    uint32 public immutable shardCount;

    mapping(address => AggregatorInfo) public aggregators;
    address[] public aggregatorSet;

    /// Chỉ số quay vòng trong `aggregatorSet`. Ai đang được chỉ định cho epoch
    /// kế tiếp thì đọc bằng `designatedAggregator()`.
    uint256 public aggRotation;

    /// Block EVM mà epoch kế tiếp phải được cam kết trước.
    uint64 public commitDeadlineBlock;

    event CollateralSlashed(
        address indexed provider, uint64 indexed epoch, uint256 slashed, uint256 owed
    );
    event CollateralWithdrawRequested(address indexed provider, uint64 unlockEpoch);
    event CollateralWithdrawn(address indexed provider, uint256 amount);
    event DealClosed(bytes32 indexed dealId, uint64 endEpoch);
    event ProviderSuspendedEvent(address indexed provider, uint256 collateralWei, uint64 usedSlots);
    event CelestiaAddressChangeRequested(address indexed provider, bytes20 newAddr, uint64 effectiveEpoch);

    event AggregatorRegistered(address indexed agg, uint256 collateralWei);
    event AggregatorTimedOut(address indexed agg, uint64 epoch, uint256 slashed, address reporter);
    event CommitDeadlineSet(uint64 indexed epoch, uint64 deadlineBlock);

    error NotDesignatedAggregator();
    error NotAggregator();
    error DeadlineNotPassed();
    error NoAggregators();
    error ProviderSuspended();
    error CapacityBelowUsage();
    error InsufficientEscrow();

    /*───────────────────────────────────────────────────────────────────────
      SỔ THÀNH VIÊN  ·  [SPEC §D.3]

      Hợp đồng KHÔNG THỂ tính deals_root — đó là O(N) on-chain. Nên tách:

        on-chain  một giá trị tích luỹ 32 byte, một keccak mỗi thao tác
        trên DA   toàn văn, namespace kind=04

      LỖ HỔNG NÓ ĐÓNG [SPEC §J.2.6]: bản trước để guest lặp trên `expected`
      mà không nói danh sách đó ở đâu ra, và hợp đồng giải mã `snapshot_id`
      rồi BỎ ĐÓ — không kiểm gì. Host bớt một hợp đồng thì hợp đồng đó không
      có phán quyết, nút mất doanh thu, KHÔNG AI PHÁT HIỆN.

      Điều bản sửa mua được không phải "phát hiện gian lận" mà là DỜI CHI PHÍ
      SAI TỪ NẠN NHÂN SANG HOST: host bỏ sót thì bằng chứng bị từ chối và nó
      đốt hàng giờ SP1 không công.
    ───────────────────────────────────────────────────────────────────────*/

    /// Tích luỹ mọi thay đổi thành viên. Cập nhật O(1), ~100 gas mỗi thao tác.
    bytes32 public membershipLog;

    /// Số hợp đồng ĐANG HOẠT ĐỘNG — cập nhật cùng lúc với membershipLog.
    ///
    /// [SỬA — nhận xét phản biện] Bản trước chỉ lưu `numVerified` từ public
    /// values rồi phát sự kiện, KHÔNG đối chiếu với gì. Guest báo numVerified=1
    /// cho một epoch có 10.000 hợp đồng thì hợp đồng vẫn nhận.
    ///
    /// Nghĩa là "một bằng chứng hợp lệ" KHÔNG đồng nghĩa "toàn bộ nghĩa vụ lưu
    /// trữ đã hoàn thành" — đúng chỗ thầy chỉ ra.
    ///
    /// Chuỗi tin cậy đầy đủ cần cả bốn mắt, và mắt thứ tư là mắt này:
    ///   ① khoá chương trình ghim cứng      → guest chạy đúng chương trình
    ///   ② snapshot_id ghim on-chain        → guest dùng đúng sổ thành viên
    ///   ③ guest dựng expected từ sổ        → không nhận danh sách từ host
    ///   ④ numVerified == activeDealCount   → guest đã xét HẾT, không bớt
    uint32 public activeDealCount;

    /// Đóng băng cùng `snapshotForCurrentEpoch`, để `numVerified` đối chiếu
    /// đúng ảnh chụp mà epoch này được chứng minh trên đó.
    uint32 public expectedDealCount;

    /// Giá trị đã đóng băng cho epoch đang chứng minh.
    ///
    /// [SPEC §D.3.5] Đóng băng tại `commitEpoch` của epoch TRƯỚC, không phải
    /// đúng biên epoch trên Celestia — vì hợp đồng EVM không đọc được chiều
    /// cao Celestia, và ở biên epoch không có giao dịch nào để kích hoạt.
    ///
    /// Hệ quả: thay đổi xảy ra giữa biên Celestia và lần commit trước sẽ rơi
    /// vào epoch hiện tại thay vì epoch sau. Rủi ro thực tế thấp vì hợp đồng
    /// phải qua `activate` mới vào tập chứng minh, mà niêm phong mất 1,26 giờ.
    bytes32 public snapshotForCurrentEpoch;

    event MembershipChanged(bytes32 indexed kind, bytes32 a, bytes32 b, bytes32 newLog);
    event SnapshotFrozen(uint64 indexed epoch, bytes32 snapshotId);

    bytes32 constant M_PROVIDER = "PROVIDER";
    bytes32 constant M_DEAL_OPEN = "DEAL_OPEN";
    bytes32 constant M_DEAL_ACTIVE = "DEAL_ACTIVE";
    bytes32 constant M_DEAL_CLOSED = "DEAL_CLOSED";

    /// Ghi một thay đổi vào sổ. Guest phát lại chuỗi này từ sự kiện on-chain
    /// và phải ra đúng cùng giá trị — bớt một mục là khác ngay.
    function _logMembership(bytes32 kind, bytes32 a, bytes32 b) internal {
        membershipLog = keccak256(abi.encodePacked(membershipLog, kind, a, b));
        emit MembershipChanged(kind, a, b, membershipLog);
    }
    uint256 public protocolFeePool;

    /*═══════════════════════════════════════════════════════════════════════
      5. SỰ KIỆN
    ═══════════════════════════════════════════════════════════════════════*/

    event ProviderRegistered(address indexed provider, bytes20 celestiaAddress, uint64 slots);
    event DealOpened(bytes32 indexed dealId, address indexed customer, address indexed provider, uint8 deadlineIdx, uint32 shard);
    event SealedRegistered(bytes32 indexed dealId, bytes32 sealedRoot, bytes32 providerRoot);
    event DealActivated(bytes32 indexed dealId);
    event DealAborted(bytes32 indexed dealId, address refundedTo);
    event EpochCommitted(uint64 indexed epoch, bytes32 newStateRoot, uint32 numVerified);
    event EpochFinalized(uint64 indexed epoch, uint64 daNonce);
    event EpochVoided(uint64 indexed epoch, string reason);
    event SettlementClaimed(bytes32 indexed leafDigest, address beneficiary, uint256 amount, uint256 bounty);

    /*═══════════════════════════════════════════════════════════════════════
      6. LỖI  — dùng custom error cho rẻ gas
    ═══════════════════════════════════════════════════════════════════════*/

    error BadCalldataLength();
    error SubmitterMismatch();     // [SPEC §D.2.4] chống front-run
    error StateRootMismatch();     // chuỗi trạng thái phải nối liền
    error VkDigestMismatch();      // [SPEC §D.2.2] NEO vào hệ chứng minh
    error EpochOutOfOrder();       // [SPEC §F.2.6] cam kết PHẢI đúng thứ tự
    error EpochNotCommitted();
    error EpochNotFinal();
    error BlobstreamRejected();
    error DealExists();
    error DealNotFound();
    error WrongState();
    error NotCustomer();
    error NotProvider();
    error InsufficientCollateral();
    error NoFreeSlots();
    error AbortTooEarly();
    error AlreadyClaimed();
    error ClaimOutOfOrder();
    error BadMerkleProof();
    error SnapshotMismatch();     // [SPEC §D.3] sổ thành viên không khớp
    error CoverageIncomplete();   // guest chưa xét hết tập hợp đồng
    error ResultsNotAvailable();  // danh sách quyết toán chưa chứng minh có trên DA

    constructor(
        IEngramVerifier _verifier,
        IBlobstream _blobstream,
        bytes32 _storageVkDigest,
        bytes32 _activationVkDigest,
        bytes32 _workerVkey,
        bytes32 _aggregatorVkey,
        bytes32 _genesisStateRoot,
        uint64 _deadlinesPerEpoch,
        uint32 _shardCount
    ) {
        require(_deadlinesPerEpoch > 0 && _shardCount > 0, "tham so lich phai duong");
        verifier = _verifier;
        blobstream = _blobstream;
        STORAGE_VK_DIGEST = _storageVkDigest;
        ACTIVATION_VK_DIGEST = _activationVkDigest;
        WORKER_PROGRAM_VKEY = _workerVkey;
        AGGREGATOR_PROGRAM_VKEY = _aggregatorVkey;
        currentStateRoot = _genesisStateRoot;
        genesisAnchor = keccak256(abi.encodePacked("ENGRAM_GENESIS_ANCHOR", _genesisStateRoot, block.chainid));
        DEADLINES_PER_EPOCH = _deadlinesPerEpoch;
        shardCount = _shardCount;
        // [T2.2-A] PHẢI khởi tạo. Để 0 thì `block.number <= 0 + VOID_GRACE_BLOCKS`
        // sai ngay trên chuỗi thật, và `voidEpoch` mở toang từ giây đầu tiên —
        // đúng lỗ hổng mà bản vá này sinh ra để đóng.
        commitDeadlineBlock = uint64(block.number) + COMMIT_PERIOD_BLOCKS;
    }

    /*═══════════════════════════════════════════════════════════════════════
      7. SỔ ĐĂNG KÝ NÚT  ·  [SPEC UC-10 / §D.1.2]

      Sổ này KIÊM danh bạ. Không có gossip, không có bootstrap node — sổ
      on-chain LÀ nguồn sự thật. Danh sách gossip là lỗ hổng Sybil rẻ tiền: kẻ
      xấu chạy một nút mồi và trả về 1.000 danh tính của chính nó. Ở đây mỗi
      danh tính tốn một khoản cọc. [SPEC §D.1.3]
    ═══════════════════════════════════════════════════════════════════════*/

    function registerProvider(
        bytes20 celestiaAddress,
        uint64 capacitySlots,
        string calldata multiaddr,
        bytes calldata celestiaOwnershipProof
    ) external payable {
        // [CHỐT B2-a] [SPEC §J.2.5] Cọc phải đủ cho số khe khai báo.
        if (msg.value < uint256(capacitySlots) * MIN_COLLATERAL_PER_SLOT) {
            revert InsufficientCollateral();
        }

        // [MỞ] Chứng minh nắm khoá Celestia. Nếu bỏ bước này, kẻ tấn công đăng
        // ký địa chỉ Celestia của người khác thành của mình và tạo nhập nhằng.
        // Hiện chỉ kiểm khác rỗng; hiện thực đầy đủ cần verify chữ ký secp256k1
        // trên một thách thức gắn với address(this) và msg.sender.
        require(celestiaOwnershipProof.length > 0, "thieu chung minh khoa Celestia");

        StorageProvider storage p = providers[msg.sender];

        // ── [R3] ĐĂNG KÝ LẠI KHÔNG ĐƯỢC PHÉP GHI ĐÈ TUỲ Ý ──────────────────
        //
        // Bản trước không phân biệt lần đầu với lần sau. Hai hệ quả:
        //
        // ① Không kiểm `capacitySlots >= usedSlots`, nên nút đăng ký lại với
        //    capacity = 0 trong khi đang giữ 5 hợp đồng, và không ai bắt.
        //
        // ② Đổi `celestiaAddress` GIỮA CHỪNG làm hỏng chính bộ lọc signer. Nút
        //    sắp bị FAIL đổi địa chỉ để blob của chính nó bị loại, biến FAIL
        //    thành ABSENT, tức NÉ MỨC PHẠT GẤP MƯỜI.
        //
        // Giờ: capacity không tụt dưới số khe đang dùng; và địa chỉ Celestia chỉ
        // đặt được ở lần đăng ký ĐẦU, sau đó phải đi qua
        // `requestCelestiaAddressChange` và chỉ hiệu lực từ epoch sau.
        if (capacitySlots < p.usedSlots) revert CapacityBelowUsage();

        if (p.celestiaAddress == bytes20(0)) {
            p.celestiaAddress = celestiaAddress;
        } else if (celestiaAddress != p.celestiaAddress) {
            revert WrongState();
        }

        p.collateralWei += msg.value;
        p.capacitySlots = capacitySlots;

        // Nạp thêm cọc đủ mức thì gỡ treo.
        if (p.suspended && p.collateralWei >= uint256(p.usedSlots) * MIN_COLLATERAL_PER_SLOT) {
            p.suspended = false;
        }
        p.multiaddr = multiaddr;
        p.registeredAtEpoch = lastCommittedEpoch + 1; // hiệu lực từ biên epoch sau

        _logMembership(M_PROVIDER, bytes32(uint256(uint160(msg.sender))),
                       bytes32(uint256(uint160(uint256(bytes32(celestiaAddress)) >> 96))));
        emit ProviderRegistered(msg.sender, celestiaAddress, capacitySlots);
    }

    /*═══════════════════════════════════════════════════════════════════════
      8. VÒNG ĐỜI HỢP ĐỒNG  ·  [SPEC UC-02]

      THỨ TỰ QUAN TRỌNG: openDeal chạy TRƯỚC khi niêm phong.

      Bản v1 để nút niêm phong trước rồi bắt khách chạy lại 1,28 giờ để đối
      chiếu. Ba vấn đề, và đảo thứ tự đóng cả ba:
        ① activation_beacon phải biết TRƯỚC khi niêm phong — ở thứ tự cũ nó
           chưa tồn tại
        ② khách không phải chạy lại; ràng buộc chuyển từ chữ ký sang bằng chứng
           kiểm lại được vĩnh viễn
        ③ đổi được hàm niêm phong mà không đụng phía khách
    ═══════════════════════════════════════════════════════════════════════*/

    /// Tham số gom vào struct thay vì 10 đối số rời.
    ///
    /// KHÔNG phải cho đẹp. Với 10 đối số cộng việc dựng `StorageDeal` 17 trường,
    /// trình biên dịch hết chỗ trên stack EVM (16 khe truy cập được) và báo
    /// "Stack too deep". Hai cách chữa:
    ///
    ///   ① bật viaIR — chữa được, nhưng ĐỔI SỐ GAS và làm biên dịch chậm hẳn.
    ///      Với bài báo lấy gas làm con số trung tâm thì đổi codegen là đổi
    ///      chính thứ đang đo.
    ///   ② gom tham số — giảm áp lực stack, giữ nguyên codegen, và tiện hơn ở
    ///      chỗ gọi vì không còn nhầm thứ tự 10 đối số cùng kiểu số.
    ///
    /// Chọn ②.
    /// [R5] Beacon kích hoạt, LẤY TỪ CELESTIA chứ không từ `blockhash`.
    ///
    /// VÌ SAO ĐỔI. Bản trước dùng `blockhash(block.number - 1)`. Người đề xuất
    /// block EVM chọn được đưa giao dịch `openDeal` vào block nào, nên chọn được
    /// một trong vài giá trị beacon gần nhau. Và nó lệch nguồn với phần còn lại
    /// của hệ: thách thức deadline lấy từ data root Celestia, chỉ riêng beacon
    /// kích hoạt lấy từ EVM.
    ///
    /// NGUỒN MỚI. `daCommitment` của epoch đã cam kết gần nhất — một giá trị đã
    /// được 2/3 cổ phần Celestia ký và Blobstream chuyển sang EVM. Người đề xuất
    /// block EVM không tác động được vào nó.
    ///
    /// ĐÁNH ĐỔI, PHẢI NÓI RÕ. Giá trị này CỐ ĐỊNH trong suốt một epoch, nên nó
    /// đoán trước được kể từ lúc epoch trước cam kết. Tính chất nó mua được là
    /// "không dựng vết niêm phong trước khi epoch trước được cam kết", KHÔNG
    /// phải "không đoán trước được trong vài giây". Về độ tươi thì yếu hơn
    /// `blockhash`; về nguồn gốc và khả năng mài thì mạnh hơn.
    ///
    /// Trộn `dealId` để hai hợp đồng trong cùng epoch không dùng chung một vết.
    function _activationBeacon(bytes32 dealId) internal view returns (bytes32) {
        bytes32 anchor = epochs[lastCommittedEpoch].daCommitment;

        // ── KHỞI ĐỘNG: chưa có epoch nào cam kết ────────────────────────────
        //
        // Bản trước revert `NoCelestiaAnchor` ở đây. Đó là một lỗi THIẾT KẾ,
        // không phải một phép kiểm an toàn: hợp đồng lưu trữ ĐẦU TIÊN không mở
        // được, mà không có hợp đồng thì không có gì để chứng minh, nên không
        // bao giờ có epoch đầu tiên. Bế tắc vòng tròn. `forge test` bắt đúng
        // điều này qua `test_phi_niem_phong_mo_khoa_khi_dang_ky_seal`.
        //
        // Neo dự phòng là `genesisAnchor`, đặt trong constructor. Nó đoán trước
        // được, nhưng ở thời điểm khởi động thì không có gì để mài: `dealId`
        // gắn với `msg.sender` và nonce của khách, nên nút không biết trước
        // trừ khi khách thông đồng — và khách thông đồng với nút của chính
        // mình thì không có ai bị hại.
        //
        // Từ epoch đầu tiên trở đi, neo là `daCommitment` đã được 2/3 cổ phần
        // Celestia ký. Nên tính chất yếu hơn CHỈ áp dụng cho những hợp đồng mở
        // trước epoch đầu tiên.
        if (anchor == bytes32(0)) anchor = genesisAnchor;

        return keccak256(
            abi.encodePacked("ENGRAM_ACT_BEACON_V1", anchor, lastCommittedEpoch, dealId)
        );
    }

    /// [T1.3] Bốn trường `dealId`, `deadlineIdx`, `shard`, `activationBeacon`
    /// ĐÃ BỎ khỏi tham số: chúng được hợp đồng dẫn xuất, không nhận từ khách.
    struct DealParams {
        address provider;
        bytes32 pieceRoot;
        uint64 pieceSizeReal;
        uint256 pricePerEpochWei;
        uint64 durationEpochs;
        uint256 sealingFeeWei;
    }

    /// [T1.3] Mở hợp đồng lưu trữ.
    ///
    /// BẢN TRƯỚC nhận `dealId`, `deadlineIdx`, `shard`, `activationBeacon` làm
    /// THAM SỐ và không kiểm gì. Đặc tả thì nói hợp đồng tự dẫn xuất
    /// `deadlineIdx = H(dealId) mod D` và `shard = H(dealId) mod S_ns`.
    ///
    /// Hệ quả nặng nhất: khách MÀI `dealId` cho tới khi hợp đồng rơi vào đúng
    /// mảnh mà kẻ tấn công đã chiếm khe worker. Hai hệ quả nhẹ hơn là lệch tải
    /// và tự chọn beacon.
    ///
    /// Giờ cả bốn trường được dẫn xuất trong hợp đồng. `dealId` gắn với
    /// `msg.sender` và một nonce tăng dần, nên không mài được: đổi bất kỳ đầu
    /// vào nào thì `dealId` đổi theo một cách khách không điều khiển nổi.
    function openDeal(DealParams calldata q) external payable returns (bytes32 dealId) {
        dealId = keccak256(
            abi.encodePacked(msg.sender, q.provider, q.pieceRoot, dealNonce[msg.sender]++)
        );
        if (_deals[dealId].state != DealState.None) revert DealExists();

        uint8 deadlineIdx = uint8(uint256(keccak256(abi.encodePacked("DL", dealId))) % DEADLINES_PER_EPOCH);
        uint32 shard = uint32(uint256(keccak256(abi.encodePacked("SH", dealId))) % shardCount);
        bytes32 activationBeacon = _activationBeacon(dealId);

        StorageProvider storage p = providers[q.provider];
        if (p.capacitySlots == 0) revert NotProvider();
        if (p.suspended) revert ProviderSuspended();          // [R2]
        if (p.usedSlots >= p.capacitySlots) revert NoFreeSlots();

        // [CHỐT B2-a] Kiểm lại tại thời điểm nhận hợp đồng, không chỉ lúc đăng ký:
        // nút có thể đã rút bớt cọc sau khi đăng ký.
        if (p.collateralWei < uint256(p.usedSlots + 1) * MIN_COLLATERAL_PER_SLOT) {
            revert InsufficientCollateral();
        }

        uint256 escrow = q.pricePerEpochWei * q.durationEpochs;
        require(msg.value == escrow + q.sealingFeeWei, "so tien khong khop");

        // Ghi qua con trỏ storage, từng trường một. Dựng cả struct trong bộ nhớ
        // rồi gán một lần cũng đúng, nhưng nó giữ 17 giá trị sống cùng lúc và
        // đó chính là thứ đẩy stack quá giới hạn.
        StorageDeal storage d = _deals[dealId];
        d.customer = msg.sender;
        d.provider = q.provider;
        d.pieceRoot = q.pieceRoot;
        d.activationBeacon = activationBeacon;
        d.pieceSizeReal = q.pieceSizeReal;
        d.slotIdx = uint32(p.usedSlots);
        d.deadlineIdx = deadlineIdx;
        d.shard = shard;
        d.pricePerEpochWei = q.pricePerEpochWei;
        d.escrowWei = escrow;
        d.sealingFeeWei = q.sealingFeeWei;
        d.startEpoch = lastCommittedEpoch + 1;
        d.endEpoch = lastCommittedEpoch + 1 + q.durationEpochs;
        // [T2.4] Ghi mốc mở. Bản trước KHÔNG BAO GIỜ gán trường này nên nó luôn
        // bằng 0, và điều kiện huỷ trong `abortDeal` luôn thoả.
        d.openedAtEpoch = lastCommittedEpoch + 1;
        d.state = DealState.Pending;

        p.usedSlots += 1;
        _logMembership(M_DEAL_OPEN, dealId, bytes32(uint256(uint160(q.provider))));
        emit DealOpened(dealId, msg.sender, q.provider, deadlineIdx, shard);
    }

    /// [SPEC UC-02 bước ⑤] Nút đăng ký gốc niêm phong.
    ///
    /// [CHỐT B1-a] [SPEC §J.2.4] Đây là chỗ phí niêm phong ĐƯỢC MỞ KHOÁ. Nút bỏ
    /// 1,28 giờ CPU trước khi kiếm được đồng nào; không có khoản này thì khách
    /// mở 1.000 hợp đồng rồi bỏ, nút đốt 1.280 giờ CPU còn khách tốn ~1 $ và lấy
    /// lại toàn bộ ký quỹ.
    function registerSealed(bytes32 dealId, bytes32 sealedRoot, bytes32 newProviderRoot) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (msg.sender != d.provider) revert NotProvider();

        d.sealedRoot = sealedRoot;
        providers[msg.sender].providerRoot = newProviderRoot;

        if (!d.sealingFeeReleased && d.sealingFeeWei > 0) {
            d.sealingFeeReleased = true;
            (bool ok,) = payable(d.provider).call{value: d.sealingFeeWei}("");
            require(ok, "chuyen phi niem phong that bai");
        }

        emit SealedRegistered(dealId, sealedRoot, newProviderRoot);
    }

    /// [SPEC §E.3] Bằng chứng kích hoạt — chạy MỘT LẦN cả đời hợp đồng.
    ///
    /// Nó đóng lỗ hổng: nút niêm phong dữ liệu TUỲ Ý rồi vẫn qua mọi thách thức
    /// định kỳ, vì mạch định kỳ chỉ có cây niêm phong, không có cây dữ liệu gốc
    /// để đối chiếu.
    ///
    /// Mạch kiểm cùng một biến nhân chứng C_j vừa nằm dưới piece_root vừa sinh
    /// ra R_j, S_j dưới sealed_root. Trong R1CS, C_j là MỘT biến, nên prover
    /// không thể dùng giá trị thật ở chỗ này và giá trị rác ở chỗ kia.
    function activate(bytes32 dealId, bytes calldata proof, bytes calldata publicValues) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (d.sealedRoot == bytes32(0)) revert WrongState();

        verifier.verifyProof(ACTIVATION_VK_DIGEST, publicValues, proof);

        d.state = DealState.Active;
        // Chỉ hợp đồng ĐÃ KÍCH HOẠT mới vào tập chứng minh, nên đây mới là
        // thời điểm nó thật sự đổi thành viên.
        activeDealCount += 1;
        _logMembership(M_DEAL_ACTIVE, dealId, bytes32(uint256(d.deadlineIdx)));
        emit DealActivated(dealId);
    }

    /// [SPEC UC-02 A3] Nút không đăng ký sealed_root trong hạn → ai gọi cũng được.
    /// Khách lấy lại TOÀN BỘ ký quỹ. Phí niêm phong chưa mở khoá nên cũng về khách.
    /// [T2.4] Khách huỷ hợp đồng chưa được niêm phong.
    ///
    /// BẢN TRƯỚC nhận `currentDeadline` TỪ CHÍNH NGƯỜI GỌI, và `openedAtDeadline`
    /// không bao giờ được gán nên luôn bằng 0. Kết quả: bất kỳ ai cũng huỷ được
    /// mọi hợp đồng đang Pending vào bất cứ lúc nào. Khách lấy lại ký quỹ, nút
    /// mất 1,26 giờ CPU niêm phong. Đây đúng là kịch bản griefing mà thiết kế
    /// định chặn.
    ///
    /// Giờ mốc thời gian lấy từ `lastCommittedEpoch`, một giá trị của hợp đồng,
    /// và chỉ khách mới gọi được.
    function abortDeal(bytes32 dealId) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Pending) revert WrongState();
        if (msg.sender != d.customer) revert WrongState();
        if (lastCommittedEpoch < d.openedAtEpoch + ABORT_AFTER_EPOCHS) revert AbortTooEarly();

        uint256 refund = d.escrowWei + (d.sealingFeeReleased ? 0 : d.sealingFeeWei);
        d.state = DealState.Aborted;
        providers[d.provider].usedSlots -= 1;

        _logMembership(M_DEAL_CLOSED, dealId, bytes32(0));
        (bool ok,) = payable(d.customer).call{value: refund}("");
        require(ok, "hoan tien that bai");
        emit DealAborted(dealId, d.customer);
    }

    /// [T2.1] Đóng hợp đồng đã hết hạn.
    ///
    /// VÌ SAO BẮT BUỘC PHẢI CÓ. `activeDealCount` chỉ tăng: nó tăng ở
    /// `registerSealed` và nhánh giảm trong `abortDeal` là CODE CHẾT theo hai
    /// cách cùng lúc — hàm đã chặn mọi state khác `Pending` ở đầu, và state đã
    /// bị gán `Aborted` trước khi nhánh đó đọc.
    ///
    /// Hệ quả nằm đúng trên đóng góp chính: mắt xích ④ đòi
    /// `numVerified == expectedDealCount`. Khi hợp đồng đầu tiên hết hạn, không
    /// prover nào tạo được đẳng thức đó nữa, và CẢ CHUỖI ĐỨNG VĨNH VIỄN.
    ///
    /// Khác mọi lỗ khác ở một điểm: cái này KHÔNG CẦN kẻ tấn công, nó tự xảy ra.
    ///
    /// Mở cho mọi người gọi: đóng một hợp đồng đã hết hạn không hại ai, và để
    /// mở thì không phụ thuộc việc khách hay nút có nhớ gọi hay không.
    function closeExpiredDeal(bytes32 dealId) external {
        StorageDeal storage d = _deals[dealId];
        if (d.state != DealState.Active) revert WrongState();
        if (lastCommittedEpoch < d.endEpoch) revert AbortTooEarly();

        d.state = DealState.Closed;
        if (activeDealCount > 0) activeDealCount -= 1;
        StorageProvider storage p = providers[d.provider];
        if (p.usedSlots > 0) p.usedSlots -= 1;

        // [R12] Hoàn phần ký quỹ CHƯA TIÊU cho khách. Không có bước này thì tiền
        // nằm lại trong hợp đồng vĩnh viễn. Từ [R1], `escrowWei` đã được trừ dần
        // mỗi lần trả thưởng, nên số còn lại đúng là phần chưa dùng.
        uint256 leftover = d.escrowWei;
        d.escrowWei = 0;

        _logMembership(M_DEAL_CLOSED, dealId, bytes32(0));
        emit DealClosed(dealId, d.endEpoch);

        if (leftover > 0) {
            (bool ok,) = payable(d.customer).call{value: leftover}("");
            require(ok, "hoan ky quy du that bai");
        }
    }

    /*═══════════════════════════════════════════════════════════════════════
      9. CAM KẾT EPOCH  ·  [SPEC §F.2.3 pha ④]

      Đây là hàm mà cả kiến trúc phục vụ. Sáu việc, theo thứ tự, tổng 474.260 gas.
    ═══════════════════════════════════════════════════════════════════════*/

    /// [R3] Xin đổi địa chỉ Celestia. Chỉ hiệu lực từ epoch SAU.
    ///
    /// Không cho đổi tức thì, vì đổi giữa chừng một epoch là một đường né phạt:
    /// blob nút đã đăng dưới địa chỉ cũ lập tức bị bộ lọc signer loại, và một
    /// phán quyết FAIL đang chờ biến thành ABSENT.
    function requestCelestiaAddressChange(bytes20 newAddr, bytes calldata ownershipProof)
        external
    {
        StorageProvider storage p = providers[msg.sender];
        if (p.capacitySlots == 0) revert NotProvider();
        require(ownershipProof.length > 0, "thieu chung minh khoa Celestia");
        p.pendingCelestiaAddress = newAddr;
        p.celestiaChangeEffectiveEpoch = lastCommittedEpoch + 2;
        emit CelestiaAddressChangeRequested(msg.sender, newAddr, p.celestiaChangeEffectiveEpoch);
    }

    /// Áp dụng thay đổi khi đã tới epoch hiệu lực. Ai gọi cũng được.
    function applyCelestiaAddressChange(address provider) external {
        StorageProvider storage p = providers[provider];
        if (p.pendingCelestiaAddress == bytes20(0)) revert WrongState();
        if (lastCommittedEpoch < p.celestiaChangeEffectiveEpoch) revert AbortTooEarly();
        p.celestiaAddress = p.pendingCelestiaAddress;
        p.pendingCelestiaAddress = bytes20(0);
        _logMembership(M_PROVIDER, bytes32(uint256(uint160(provider))),
                       bytes32(uint256(uint160(uint256(bytes32(p.celestiaAddress)) >> 96))));
    }

    // ═══════════════════════════════════════════════════════════════════
    //  CỌC NHÀ CUNG CẤP: xin rút, khoá, rút   [T3.4-A]
    // ═══════════════════════════════════════════════════════════════════
    //
    // BẢN TRƯỚC khai `withdrawRequestedAtEpoch` và `COLLATERAL_LOCK_EPOCHS` mà
    // KHÔNG HÀM NÀO DÙNG. Mã mô tả một cơ chế không tồn tại là loại tài liệu sai
    // nguy hiểm nhất, vì nó đọc như đã làm rồi.

    /// Xin rút cọc. Bắt đầu đếm khoá.
    ///
    /// Vì sao cần khoá: phán quyết của epoch e chỉ rút được sau khi epoch đó
    /// `Final`, tức trễ tới hai epoch. Cho rút ngay thì nút xoá dữ liệu, xin rút,
    /// lấy cọc về TRƯỚC khi lá phạt của nó kịp lên chuỗi.
    function requestCollateralWithdraw() external {
        StorageProvider storage p = providers[msg.sender];
        if (p.capacitySlots == 0) revert NotProvider();
        p.withdrawRequestedAtEpoch = lastCommittedEpoch;
        emit CollateralWithdrawRequested(msg.sender, lastCommittedEpoch + COLLATERAL_LOCK_EPOCHS);
    }

    /// Rút phần cọc KHÔNG bị ràng buộc bởi khe đang dùng.
    function withdrawCollateral(uint256 amount) external {
        StorageProvider storage p = providers[msg.sender];
        if (p.capacitySlots == 0) revert NotProvider();
        if (p.withdrawRequestedAtEpoch == 0) revert WrongState();
        if (lastCommittedEpoch < p.withdrawRequestedAtEpoch + COLLATERAL_LOCK_EPOCHS) {
            revert AbortTooEarly();
        }
        // Giữ lại đủ cọc cho mọi khe đang dùng, nếu không thì hợp đồng đang chạy
        // mất neo kinh tế ngay giữa chừng.
        uint256 locked = uint256(p.usedSlots) * MIN_COLLATERAL_PER_SLOT;
        if (p.collateralWei < locked + amount) revert InsufficientCollateral();

        p.collateralWei -= amount;
        p.withdrawRequestedAtEpoch = 0;
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        require(ok, "rut coc that bai");
        emit CollateralWithdrawn(msg.sender, amount);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  AGGREGATOR  ·  đăng ký, chỉ định, phạt khi im lặng   [T2.3-B]
    // ═══════════════════════════════════════════════════════════════════

    function registerAggregator() external payable {
        AggregatorInfo storage a = aggregators[msg.sender];
        if (msg.value + a.collateralWei < MIN_AGG_COLLATERAL) revert InsufficientCollateral();
        if (!a.registered) {
            a.registered = true;
            aggregatorSet.push(msg.sender);
        }
        a.collateralWei += msg.value;
        emit AggregatorRegistered(msg.sender, a.collateralWei);
    }

    /// Ai được chỉ định cam kết epoch kế tiếp.
    ///
    /// Quay vòng chứ không cố định: aggregator cố định mà im lặng thì cả chuỗi
    /// kẹt, và không có đường thay người.
    function designatedAggregator() public view returns (address) {
        uint256 n = aggregatorSet.length;
        if (n == 0) return address(0);
        // [T2.3-B, vá vòng rà] BỎ QUA aggregator đã tụt dưới cọc tối thiểu.
        //
        // Không có bước này thì có một đòn tính sống rẻ: đăng ký nhiều địa chỉ
        // rồi rút hết cọc lúc không được chỉ định. Địa chỉ rỗng vẫn nằm trong
        // tập, vẫn tới lượt, và `reportAggregatorTimeout` cắt 10 % của 0 = 0.
        // Mỗi xác sống như vậy đốt trọn một kỳ COMMIT_PERIOD_BLOCKS.
        for (uint256 i = 0; i < n; i++) {
            address cand = aggregatorSet[(aggRotation + i) % n];
            if (aggregators[cand].collateralWei >= MIN_AGG_COLLATERAL) return cand;
        }
        return address(0);
    }

    /// Báo aggregator được chỉ định đã để lỡ hạn.
    ///
    /// KHÔNG huỷ epoch. Chỉ cắt cọc người được chỉ định, chuyển lượt cho người
    /// kế tiếp, và gia hạn. Epoch vẫn cam kết được — đây là chỗ khác căn bản so
    /// với `voidEpoch`, vốn vứt bỏ công sức của cả mạng trong một ngày.
    function reportAggregatorTimeout(uint64 epoch) external {
        if (epoch != lastCommittedEpoch + 1) revert EpochOutOfOrder();

        // [T2.3-B] Trong hạn thì chỉ người được chỉ định nộp được. Quá hạn thì
        // MỞ CHO MỌI NGƯỜI — tính sống quan trọng hơn việc giữ độc quyền, và
        // người được chỉ định đã bị cắt cọc qua `reportAggregatorTimeout`.
        address designated = designatedAggregator();
        if (
            designated != address(0)
            && block.number <= commitDeadlineBlock
            && msg.sender != designated
        ) revert NotDesignatedAggregator();
        if (block.number <= commitDeadlineBlock) revert DeadlineNotPassed();
        if (aggregatorSet.length == 0) revert NoAggregators();

        address agg = designatedAggregator();
        AggregatorInfo storage a = aggregators[agg];

        if (agg == address(0)) revert NoAggregators();

        uint256 slashed = (a.collateralWei * AGG_TIMEOUT_SLASH_BPS) / 10_000;
        if (slashed > a.collateralWei) slashed = a.collateralWei;
        a.collateralWei -= slashed;
        a.timeouts += 1;

        // Chuyển lượt TRƯỚC khi gửi tiền, để người báo không thể quay lại gọi
        // tiếp trong cùng một giao dịch mà vẫn nhắm đúng nạn nhân cũ.
        aggRotation += 1;
        commitDeadlineBlock = uint64(block.number) + COMMIT_PERIOD_BLOCKS;

        uint256 bounty = (slashed * BOUNTY_BPS) / 10_000;
        if (bounty > 0) {
            (bool ok,) = payable(msg.sender).call{value: bounty}("");
            require(ok, "chuyen hoa hong that bai");
        }
        emit AggregatorTimedOut(agg, epoch, slashed, msg.sender);
        emit CommitDeadlineSet(epoch, commitDeadlineBlock);
    }

    /// [R6] Xin rút cọc aggregator. Bắt đầu đếm khoá.
    function requestAggregatorWithdraw() external {
        AggregatorInfo storage a = aggregators[msg.sender];
        if (!a.registered) revert NotAggregator();
        a.withdrawRequestedAtEpoch = lastCommittedEpoch;
    }

    /// Rút cọc aggregator.
    ///
    /// BẢN TRƯỚC chỉ chặn người ĐANG được chỉ định. Aggregator biết mình sắp tới
    /// lượt thì rút trước, tới lượt thì im lặng, và `reportAggregatorTimeout`
    /// không còn gì để cắt.
    ///
    /// Giờ dùng lại đúng mẫu khoá của cọc nhà cung cấp: xin rút, chờ
    /// COLLATERAL_LOCK_EPOCHS epoch, rồi mới rút. Trong khoảng đó nếu tới lượt
    /// mà im lặng thì vẫn bị cắt.
    function withdrawAggregatorCollateral(uint256 amount) external {
        AggregatorInfo storage a = aggregators[msg.sender];
        if (!a.registered) revert NotAggregator();
        if (msg.sender == designatedAggregator()) revert WrongState();
        if (a.withdrawRequestedAtEpoch == 0) revert WrongState();
        if (lastCommittedEpoch < a.withdrawRequestedAtEpoch + COLLATERAL_LOCK_EPOCHS) {
            revert AbortTooEarly();
        }
        if (amount > a.collateralWei) revert InsufficientCollateral();
        a.collateralWei -= amount;
        a.withdrawRequestedAtEpoch = 0;
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        require(ok, "rut coc that bai");
    }

    function commitEpoch(uint64 epoch, bytes calldata proof, bytes calldata publicValues) external {
        // ① Độ dài calldata cố định — public values LUÔN là 297 byte.
        //    Đệm ABI làm tròn 297 lên 320 hệt như 296, nên byte thứ 297 KHÔNG
        //    làm tăng độ dài calldata thật và KHÔNG đổi phí giao dịch cơ bản.
        if (publicValues.length != 297) revert BadCalldataLength();

        PublicValues memory pv = _decodePublicValues(publicValues);

        // ② [SPEC §D.2.4] Chống front-run. Không có 20 byte này thì ai đó theo
        //    dõi mempool, sao chép giao dịch của aggregator, đẩy phí cao hơn và
        //    nộp trước — cướp phần thưởng của người đã bỏ hàng giờ chứng minh.
        if (pv.submitter != msg.sender) revert SubmitterMismatch();

        // ③ [SPEC §F.2.6] Chuỗi trạng thái phải nối liền, và các epoch PHẢI cam
        //    kết ĐÚNG THỨ TỰ. Chứng minh chạy song song được (đường ống độ sâu
        //    L=2), nhưng commitEpoch thì không: epoch e chậm là e+1 phải chờ.
        //    Đó là cái giá của bất biến chuỗi trạng thái, và nó đáng giữ.
        if (epoch != lastCommittedEpoch + 1) revert EpochOutOfOrder();
        if (pv.prevStateRoot != currentStateRoot) revert StateRootMismatch();
        if (pv.epoch != epoch) revert EpochOutOfOrder();

        // ④ [SPEC §D.2.2] NEO VÀO HỆ CHỨNG MINH. Đọc comment ở mục 1.
        if (pv.storageVkDigest != STORAGE_VK_DIGEST) revert VkDigestMismatch();

        // ④b [SPEC §D.3] NEO VÀO SỔ THÀNH VIÊN.
        //
        // Không có phép kiểm này thì `snapshot_id` chỉ là 32 byte trang trí:
        // host trình gì cũng được, và bỏ sót hợp đồng thành vô hình.
        if (pv.snapshotId != snapshotForCurrentEpoch) revert SnapshotMismatch();

        // ④c [SỬA] GUEST ĐÃ XÉT HẾT CHƯA.
        //
        // Không có phép kiểm này thì guest báo numVerified=1 cho epoch có
        // 10.000 hợp đồng và hợp đồng vẫn nhận — "một bằng chứng hợp lệ"
        // không đồng nghĩa "toàn bộ nghĩa vụ đã hoàn thành".
        if (pv.numVerified != expectedDealCount) revert CoverageIncomplete();

        // ⑤ Phép tính nặng nhất. Bằng chứng KHÔNG chứa 296 byte — nó chỉ cam kết
        //    vào BĂM của chúng. 296 byte đi riêng qua calldata, hợp đồng băm lại
        //    rồi đối chiếu. [SPEC Hình D.2]
        verifier.verifyProof(AGGREGATOR_PROGRAM_VKEY, publicValues, proof);

        // ⑥ Ghi trạng thái.
        epochs[epoch] = EpochRecord({
            state: EpochState.Committed,
            batchRoot: pv.batchRoot,
            resultsRoot: pv.resultsRoot,
            resultsDataRoot: pv.resultsDataRoot,
            daCommitment: pv.daCommitment,
            daNonce: pv.daNonce,
            newStateRoot: pv.newStateRoot,
            numVerified: pv.numVerified,
            windowSaturation: pv.windowSaturation,
            submitter: msg.sender
        });
        currentStateRoot = pv.newStateRoot;
        lastCommittedEpoch = epoch;

        // [T2.3-B] Đặt hạn chót cho epoch KẾ TIẾP, và chuyển lượt aggregator.
        commitDeadlineBlock = uint64(block.number) + COMMIT_PERIOD_BLOCKS;
        if (aggregatorSet.length > 0) aggRotation += 1;
        emit CommitDeadlineSet(epoch + 1, commitDeadlineBlock);

        // Đóng băng sổ cho epoch KẾ TIẾP. Đây là thời điểm gần biên epoch nhất
        // mà hợp đồng thật sự chạy — xem ghi chú ở `snapshotForCurrentEpoch`.
        snapshotForCurrentEpoch = membershipLog;
        expectedDealCount = activeDealCount;
        emit SnapshotFrozen(epoch + 1, membershipLog);

        emit EpochCommitted(epoch, pv.newStateRoot, pv.numVerified);
    }

    /*═══════════════════════════════════════════════════════════════════════
      10. CHUNG KẾT  ·  [SPEC §F.2.4]

      VÌ SAO TÁCH KHỎI commitEpoch: Blobstream cập nhật mặc định MỖI GIỜ bởi bên
      vận hành thứ ba. Nếu gộp làm một thì độ trễ quyết toán của Engram có sàn
      cứng một giờ, và mọi sự cố relay thành sự cố của mình.

      Tách ra: chuỗi trạng thái tiến đúng nhịp ở commitEpoch; relay chậm chỉ hoãn
      RÚT TIỀN chứ không hoãn GHI NHẬN; relay chết hẳn thì epoch treo ở Committed
      mà KHÔNG AI MẤT GÌ.
    ═══════════════════════════════════════════════════════════════════════*/

    function finalizeEpoch(
        uint64 epoch,
        uint256 blobstreamNonce,
        IBlobstream.DataRootTuple calldata tuple_,
        IBlobstream.BinaryMerkleProof calldata proof
    ) external {
        EpochRecord storage e = epochs[epoch];
        if (e.state != EpochState.Committed) revert EpochNotCommitted();
        if (e.daNonce != uint64(blobstreamNonce)) revert BlobstreamRejected();

        // [SỬA — nhận xét phản biện] DANH SÁCH QUYẾT TOÁN PHẢI CHỨNG MINH ĐƯỢC
        // LÀ CÓ TRÊN DA.
        //
        // Bản trước giải mã `results_data_root` rồi BỎ ĐÓ. Hệ quả: aggregator
        // cam kết một `results_root` mà danh sách đầy đủ không ai tải về được,
        // nên không ai rút tiền được và cũng không ai chứng minh được nó sai.
        //
        // Giờ tuple Blobstream phải trỏ ĐÚNG data_root của block chứa danh
        // sách quyết toán. Chứng thực Blobstream vì thế bao luôn tính sẵn có
        // của manifest, không chỉ của các blob bằng chứng.
        if (tuple_.dataRoot != e.resultsDataRoot) revert ResultsNotAvailable();

        if (!blobstream.verifyAttestation(blobstreamNonce, tuple_, proof)) {
            revert BlobstreamRejected();
        }
        e.state = EpochState.Final;
        emit EpochFinalized(epoch, e.daNonce);
    }

    /*═══════════════════════════════════════════════════════════════════════
      11. QUYẾT TOÁN KÉO  ·  [SPEC §I.1.1 / §D.1.6]

      Hợp đồng KHÔNG chủ động phân phối. Người nhận tự nộp lá, đường Merkle, chỉ
      số; hợp đồng dựng lại gốc, so với resultsRoot, ghi nullifier, chuyển tiền.

      Toàn bộ N lá nằm trên DA; on-chain CHỈ CÓ gốc Merkle 32 byte. Đó là chỗ
      O(N) biến thành O(1).
    ═══════════════════════════════════════════════════════════════════════*/

    /// [SPEC §I.1.2 — SỬA D1] Rút tiền theo lá quyết toán.
    ///
    /// ── LỖ HỔNG BẢN TRƯỚC, VÀ VÌ SAO NÓ NGHIÊM TRỌNG ───────────────────────
    ///
    /// Bản trước nhận `leafDigest` ĐÃ BĂM SẴN cùng `beneficiary`, `rewardWei`,
    /// `slashWei` làm tham số rời, rồi chỉ kiểm `leafDigest` có nằm trong cây
    /// Merkle hay không.
    ///
    /// Phép kiểm đó chứng minh "digest này có trong cây". Nó KHÔNG chứng minh
    /// "digest này ứng với số tiền và người nhận vừa truyền vào". Danh sách
    /// quyết toán công bố trên DA nên ai cũng dựng được một cặp (digest, đường
    /// Merkle) hợp lệ, rồi điền `beneficiary` là ví mình và `rewardWei` bằng cả
    /// số dư hợp đồng. Giao dịch đi qua mọi phép kiểm. Rút sạch.
    ///
    /// ── CÁCH VÁ ────────────────────────────────────────────────────────────
    ///
    /// Nhận CÁC TRƯỜNG của lá, tự băm lại, rồi mới leo cây. Digest và số tiền
    /// không còn rời nhau được. Bỏ luôn tham số `beneficiary`: tiền đi tới địa
    /// chỉ `provider` ghi TRONG lá, không tới địa chỉ người gọi tự khai.
    /// [T3.5] Gom các trường của lá vào một struct thay vì 10 tham số rời.
    /// Không phải thẩm mỹ: 10 tham số cộng biến cục bộ làm tràn stack EVM, và
    /// đó chính là lỗi mà bản trước gặp phải khi thêm phần trừ cọc.
    struct LeafClaim {
        uint64 epoch;
        address provider;
        bytes32 dealId;
        uint8 verdict;
        uint32 challengesTotal;
        uint32 challengesPassed;
        uint256 rewardWei;
        uint256 slashWei;
    }

    function claimSettlement(
        LeafClaim calldata c,
        bytes32[] calldata merkleProof,
        uint256 leafIndex
    ) external {
        EpochRecord storage e = epochs[c.epoch];
        if (e.state != EpochState.Final) revert EpochNotFinal();

        bytes32 leafDigest = _leafDigest(
            c.epoch, c.provider, c.dealId, c.verdict,
            c.challengesTotal, c.challengesPassed, c.rewardWei, c.slashWei
        );
        if (settlementClaimed[leafDigest]) revert AlreadyClaimed();

        // ── [R4] QUY TẮC KHAI TUẦN TỰ ĐÃ BỎ ────────────────────────────
        //
        // Bản trước đòi `lastClaimedEpoch + 1 == epoch`. Mục đích ban đầu của nó
        // là chống khai lại. Nhưng từ bản vá D1, `epoch` đã nằm TRONG ảnh trước
        // của lá, nên `settlementClaimed[leafDigest]` một mình đã chống khai lại
        // đủ: mỗi lá chỉ rút được một lần, vĩnh viễn.
        //
        // Giữ quy tắc tuần tự thì nó chỉ còn tác hại: nếu epoch 6 bị `voidEpoch`
        // hoặc nút không có lá nào ở epoch 6, thì mọi phần thưởng từ epoch 7 trở
        // đi KHÔNG RÚT ĐƯỢC VĨNH VIỄN, vì không có gì để khai cho epoch 6.
        //
        // `lastClaimedEpoch` vẫn ghi để tiện theo dõi, nhưng không còn là điều
        // kiện.

        if (_merkleRoot(leafDigest, merkleProof, leafIndex) != e.resultsRoot) {
            revert BadMerkleProof();
        }

        settlementClaimed[leafDigest] = true;
        if (c.epoch > lastClaimedEpoch[c.provider]) lastClaimedEpoch[c.provider] = c.epoch;

        // ── [T1.2-A] TRỪ CỌC THẬT ──────────────────────────────────────
        //
        // BẢN TRƯỚC: `slashWei` chỉ dùng để TÍNH hoa hồng, không trừ cọc của ai
        // cả, và hoa hồng được chi từ số dư hợp đồng. Hai hệ quả:
        //   ① nút bị phán FAIL KHÔNG MẤT GÌ, nên toàn bộ lập luận kinh tế dựa
        //      trên mức phạt gấp 10 lần doanh thu là lập luận về một cơ chế
        //      KHÔNG TỒN TẠI on-chain;
        //   ② lá phạt thành một đường RÚT TIỀN: hoa hồng chi từ ký quỹ của
        //      người khác.
        //
        // Giờ cắt từ `collateralWei` của chính nút bị phạt, và cắt tối đa bằng
        // số cọc thực có. Hoa hồng chỉ trả trong phạm vi số đã cắt được, nên
        // hợp đồng không bao giờ chi nhiều hơn số nó vừa thu.
        uint256 slashed = 0;
        if (c.slashWei > 0) {
            StorageProvider storage sp = providers[c.provider];
            slashed = c.slashWei > sp.collateralWei ? sp.collateralWei : c.slashWei;
            sp.collateralWei -= slashed;
            emit CollateralSlashed(c.provider, c.epoch, slashed, c.slashWei);

            // [R2] Phép kiểm cọc chỉ chạy lúc NHẬN hợp đồng mới, nên nút đã bị
            // cắt xuống dưới ngưỡng vẫn giữ nguyên các hợp đồng đang chạy, và
            // chúng mất neo kinh tế: lần FAIL sau không còn gì để cắt.
            if (sp.collateralWei < uint256(sp.usedSlots) * MIN_COLLATERAL_PER_SLOT) {
                sp.suspended = true;
                emit ProviderSuspendedEvent(c.provider, sp.collateralWei, sp.usedSlots);
            }
        }

        uint256 bounty = 0;
        if (
            slashed > 0
            && msg.sender != c.provider
            // [SPEC §H.1.7] Không trả hoa hồng cho epoch mà cửa sổ DA bị lấp đầy.
            // Khi đó lá phạt không phân biệt được "nút gian" với "nút bị chặn
            // không đăng được", nên treo tiền cho người săn là trả công cho
            // chính kẻ gây nghẽn. Mức phạt giữ nguyên; chỉ phần THU bị cắt.
            && e.windowSaturation < WINDOW_SATURATION_THRESHOLD
        ) {
            // Lá PHẠT: không ai muốn nộp, nên mở cho mọi người kèm hoa hồng.
            bounty = (slashed * BOUNTY_BPS) / 10_000;
        }
        // ── [R1] TRỪ KÝ QUỸ CỦA CHÍNH HỢP ĐỒNG ĐÓ ──────────────────────
        //
        // BẢN TRƯỚC không tham chiếu `escrowWei` một lần nào trong hàm này: thưởng
        // trả từ quỹ chung, không có kế toán theo hợp đồng. Ba hệ quả: ký quỹ
        // không bao giờ bị trừ nên hợp đồng không biết một deal đã tiêu hết tiền
        // chưa; một lá với `rewardWei` bất thường vẫn được trả miễn nằm trong
        // cây; và tổng chi có thể vượt tổng thu, chỉ lộ ra khi một `call` thất
        // bại.
        //
        // Giờ mỗi lần trả là một lần trừ, và trừ không đủ thì revert. An toàn
        // chuyển từ "tin guest tính đúng" sang "hợp đồng tự kiểm".
        if (c.rewardWei > 0) {
            StorageDeal storage dl = _deals[c.dealId];
            if (dl.escrowWei < c.rewardWei) revert InsufficientEscrow();
            dl.escrowWei -= c.rewardWei;
        }

        uint256 net = c.rewardWei > bounty ? c.rewardWei - bounty : 0;

        if (net > 0) {
            (bool ok,) = payable(c.provider).call{value: net}("");
            require(ok, "chuyen thuong that bai");
        }
        if (bounty > 0) {
            (bool ok2,) = payable(msg.sender).call{value: bounty}("");
            require(ok2, "chuyen hoa hong that bai");
        }
        emit SettlementClaimed(leafDigest, c.provider, net, bounty);
    }

    /*═══════════════════════════════════════════════════════════════════════
      12. CẦU DAO  ·  [SPEC §H.1.6]

      Cơ chế phạt giả định các lỗi ĐỘC LẬP. Sự cố hạ tầng thì TƯƠNG QUAN: Celestia
      nghẽn thì MỌI nút cùng lỡ cửa sổ. Không có cầu dao, một sự cố 20 phút ghi
      NONE cho hàng nghìn hợp đồng cùng lúc.

      [MỞ] θ chỉ an toàn khi tập worker đủ lớn. Nếu mạng chỉ có 16 worker thì DoS
      16 máy là dừng được cả mạng — và 107.136 $/ngày để lấp namespace trở thành
      con số vô nghĩa vì không ai chọn đường đắt. Ngưỡng worker tối thiểu CHƯA QUYẾT.
    ═══════════════════════════════════════════════════════════════════════*/

    function voidEpoch(uint64 epoch) external {
        // [T2.2-A] BẢN TRƯỚC KHÔNG KIỂM GÌ CẢ.
        //
        // Ai cũng gọi được, chỉ cần epoch chưa Final, tốn ~30.000 gas là vô hiệu
        // hoá vĩnh viễn. Một cơ chế vừa là đường thoát vừa là vũ khí thì chưa
        // phải cơ chế.
        //
        // Giờ `voidEpoch` là CHỐT CHẶN CUỐI, không phải đường thoát thường:
        // `reportAggregatorTimeout` mới là đường thường, và nó KHÔNG vứt bỏ
        // epoch mà chỉ đổi người. Chỉ khi đã quá hạn cộng ân hạn mà vẫn không ai
        // cam kết nổi thì mới huỷ.
        if (block.number <= commitDeadlineBlock + VOID_GRACE_BLOCKS) {
            revert DeadlineNotPassed();
        }
        EpochRecord storage e = epochs[epoch];
        if (e.state == EpochState.Final) revert WrongState();
        e.state = EpochState.Void;
        emit EpochVoided(epoch, "qua han commitEpoch va het an han");
    }

    /*═══════════════════════════════════════════════════════════════════════
      13. NỘI BỘ
    ═══════════════════════════════════════════════════════════════════════*/

    struct PublicValues {
        uint64 epoch;
        bytes32 batchRoot;
        bytes32 daCommitment;
        uint64 daNonce;
        bytes32 resultsRoot;
        bytes32 resultsDataRoot;
        bytes32 storageVkDigest;
        bytes32 snapshotId;
        address submitter;
        bytes32 prevStateRoot;
        bytes32 newStateRoot;
        uint32 numVerified;
        uint8 windowSaturation;
    }

    /// [SPEC §D.2.1] Bố cục 297 byte. Định nghĩa MỘT LẦN và phải khớp bit-để-bit
    /// với `engram_common/public_values.py`. Có kiểm thử đối chiếu hai phía.
    function _decodePublicValues(bytes calldata b) internal pure returns (PublicValues memory pv) {
        pv.epoch           = uint64(bytes8(b[0:8]));
        pv.batchRoot       = bytes32(b[8:40]);
        pv.daCommitment    = bytes32(b[40:72]);
        pv.daNonce         = uint64(bytes8(b[72:80]));
        pv.resultsRoot     = bytes32(b[80:112]);
        pv.resultsDataRoot = bytes32(b[112:144]);
        pv.storageVkDigest = bytes32(b[144:176]);
        pv.snapshotId      = bytes32(b[176:208]);
        pv.submitter       = address(bytes20(b[208:228]));
        pv.prevStateRoot   = bytes32(b[228:260]);
        pv.newStateRoot    = bytes32(b[260:292]);
        pv.numVerified     = uint32(bytes4(b[292:296]));
        pv.windowSaturation = uint8(b[296]);
    }

    /// [SPEC §A.5.2] Leo cây Merkle. Hướng rẽ theo bit của chỉ số lá.
    /// [SỬA D2] Tiền tố tách miền cho NÚT TRONG.
    ///
    /// Không có nó, nút trong và lá đều chỉ là 32 byte băm, nên kẻ tấn công
    /// trình MỘT NÚT TRONG ra như thể nó là lá, kèm đường Merkle ngắn hơn, và
    /// phép kiểm vẫn khớp gốc. Lá được tách miền ở phía kia bằng nhãn
    /// ENGRAM_LEAF_V1 trong `_leafDigest`, nên hai dạng ảnh trước không trùng.
    bytes1 private constant NODE_TAG = 0x01;

    function _merkleRoot(bytes32 leaf, bytes32[] calldata proof, uint256 index)
        internal pure returns (bytes32)
    {
        bytes32 node = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            node = (index & 1) == 0
                ? keccak256(abi.encodePacked(NODE_TAG, node, proof[i]))
                : keccak256(abi.encodePacked(NODE_TAG, proof[i], node));
            index >>= 1;
        }
        return node;
    }

    /// [SPEC §D.1.6 — SỬA D1] Băm lại lá TỪ CÁC TRƯỜNG, không nhận digest sẵn.
    ///
    /// Phải khớp bit-để-bit với `SettlementLeaf.digest()` trong
    /// `aggregator/aggregate.py`. `abi.encodePacked` là big-endian, và phía
    /// Python đã đổi sang big-endian cho đúng — trước đây nó là little-endian.
    function _leafDigest(
        uint64 epoch,
        address provider,
        bytes32 dealId,
        uint8 verdict,
        uint32 challengesTotal,
        uint32 challengesPassed,
        uint256 rewardWei,
        uint256 slashWei
    ) internal pure returns (bytes32) {
        return keccak256(
            abi.encodePacked(
                "ENGRAM_LEAF_V1",
                epoch,
                provider,
                dealId,
                verdict,
                challengesTotal,
                challengesPassed,
                rewardWei,
                slashWei
            )
        );
    }

    receive() external payable {}
}
