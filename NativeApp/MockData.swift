import Foundation
import CoreLocation
import Observation
import Security

enum RecommendationDecision: Sendable {
    case none
    case top1(TopPick)
    case ask(HelpRequest)

    var isEmpty: Bool {
        if case .none = self {
            return true
        }
        return false
    }
}

struct RecommendationResult: Sendable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistory]
    let decision: RecommendationDecision
    let serviceNotice: ServiceNotice?
}

struct ServiceNotice: Equatable, Sendable {
    let title: String
    let detail: String

    var isRetryable: Bool {
        title == "皮皮" && detail.contains("重试")
    }
}

struct QuestionHistory: Identifiable, Hashable, Sendable {
    let id: UUID
    let query: String
    let status: String
    let helpRequestId: UUID?
    let topPick: TopPick?

    var statusLabel: String {
        switch status {
        case "completed":
            "已完成"
        case "top1":
            "已给选择"
        case "waiting_for_human":
            "等人来一句"
        case "answer_received":
            "已收到一句"
        default:
            "处理中"
        }
    }
}

enum HistoryDestination {
    case result
    case ask
}

struct TopPick: Hashable, Sendable {
    let cardId: UUID?
    let query: String
    let preface: String
    let title: String
    let subtitle: String
    let reason: String
    let bullets: [String]
    let warning: String
    let followups: [String]
    let referenceImage: ReferenceImage?
}

struct ReferenceImage: Hashable, Sendable {
    let url: String
    let sourceURL: String?
    let sourceDomain: String?
    let caption: String?
    let isAiGenerated: Bool
}

enum HelpRequestStatus: String, Codable, Hashable, Sendable {
    case draft
    case published
    case answered
    case completed

    var label: String {
        switch self {
        case .draft:
            "待发布"
        case .published:
            "已发布"
        case .answered:
            "已收到一句"
        case .completed:
            "已采纳"
        }
    }
}

struct HumanAnswer: Identifiable, Hashable, Sendable {
    let id: UUID
    let text: String
    let nickname: String
    let timeLabel: String

    init(id: UUID = UUID(), text: String, nickname: String, timeLabel: String) {
        self.id = id
        self.text = text
        self.nickname = nickname
        self.timeLabel = timeLabel
    }
}

struct HelpRequest: Identifiable, Hashable, Sendable {
    let id: UUID
    var title: String
    var context: String
    var rewardLabel: String
    var answerCount: Int
    var status: HelpRequestStatus
    var answers: [HumanAnswer]

    init(
        id: UUID = UUID(),
        title: String,
        context: String,
        rewardLabel: String = "+10",
        answerCount: Int = 0,
        status: HelpRequestStatus = .draft,
        answers: [HumanAnswer] = []
    ) {
        self.id = id
        self.title = title
        self.context = context
        self.rewardLabel = rewardLabel
        self.answerCount = answerCount
        self.status = status
        self.answers = answers
    }
}

enum SubmitState: Equatable {
    case idle
    case loading
}

struct DecisionLocationContext: Equatable, Sendable {
    let label: String
    let city: String?
    let area: String?
    let latitude: Double?
    let longitude: Double?
    let source: String

    var displayLabel: String {
        label.isEmpty ? "选择地点" : label
    }

    var detailLabel: String {
        switch source {
        case "current":
            "当前定位"
        case "manual":
            "手动地点"
        default:
            "决策地点"
        }
    }

    static func manual(_ rawValue: String) -> DecisionLocationContext? {
        let label = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !label.isEmpty else { return nil }

        let cityCandidates = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "南京", "苏州", "武汉", "西安", "长沙", "厦门", "大同"]
        let city = cityCandidates.first { label.localizedCaseInsensitiveContains($0) }
        let area = city == label ? nil : label
        return DecisionLocationContext(
            label: label,
            city: city,
            area: area,
            latitude: nil,
            longitude: nil,
            source: "manual"
        )
    }
}

enum CardFeedbackAction: String, Sendable {
    case reject
    case change
    case askHuman = "ask-human"

    var endpointPath: String {
        rawValue
    }
}

protocol RecommendationService: Sendable {
    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult
    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest
    func refresh(_ request: HelpRequest) async -> HelpRequest
    func fetchHelpRequest(id: UUID) async -> HelpRequest?
    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest]
    func answer(_ text: String, for request: HelpRequest) async -> HelpRequest
    func acceptCard(id: UUID?) async -> Bool
    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool
    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory]
}

enum AppAPIEnvironment {
    static let baseURL: URL = {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
           let url = URL(string: configured),
           !configured.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return url
        }
        return URL(string: "http://67.230.169.161:8788")!
    }()
}

struct BackendRecommendationService: RecommendationService {
    private let baseURL = AppAPIEnvironment.baseURL
    private let deviceUid = DeviceIdentity.uid

    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult {
        do {
            let payload = try await submitChatTurn(query: query, conversationId: sessionId, locationContext: locationContext)
            return payload.result(for: query)
        } catch {
            if shouldRetryWithFreshConversation(after: error, sessionId: sessionId) {
                do {
                    let payload = try await submitChatTurn(query: query, conversationId: nil, locationContext: locationContext)
                    return payload.result(for: query)
                } catch {
                    print("BackendRecommendationService.submit retry failed: \(error)")
                }
            }

            print("BackendRecommendationService.submit failed: \(error)")
            return RecommendationResult(
                sessionId: sessionId,
                questionId: nil,
                history: [],
                decision: .none,
                serviceNotice: MockData.backendUnavailableNotice(error: error)
            )
        }
    }

    private func submitChatTurn(
        query: String,
        conversationId: UUID?,
        locationContext: DecisionLocationContext?
    ) async throws -> V1ChatTurnResponse {
        return try await perform(makeRequest(
            path: "/v1/chat/turn",
            method: "POST",
            body: V1ChatTurnRequest(
                message: query,
                conversationId: conversationId?.uuidString,
                deviceId: deviceUid,
                clientContext: V1ClientContext(
                    source: "ios",
                    location: locationContext.flatMap(V1ClientLocation.init(context:)),
                    decisionLocation: locationContext.map(V1DecisionLocationContext.init(context:))
                ),
                metadata: [:]
            )
        ))
    }

    func publish(_ helpRequest: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest {
        do {
            let response: V1ChatTurnResponse = try await perform(makeRequest(
                path: "/v1/chat/turn",
                method: "POST",
                body: V1ChatTurnRequest(
                    message: "发出去",
                    conversationId: sessionId?.uuidString,
                    deviceId: deviceUid,
                    clientContext: V1ClientContext(source: "ios", location: nil, decisionLocation: nil),
                    metadata: ["help_card_id": helpRequest.id.uuidString]
                )
            ))
            return response.helpCards?.first?.model(fallbackTitle: helpRequest.title) ?? publishedFallback(helpRequest)
        } catch {
            return publishedFallback(helpRequest)
        }
    }

    func refresh(_ helpRequest: HelpRequest) async -> HelpRequest {
        guard helpRequest.status == .published else { return helpRequest }

        do {
            var components = URLComponents(url: endpoint("/v1/light-events"), resolvingAgainstBaseURL: false)!
            components.queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            guard let url = components.url else { return helpRequest }
            let response: V1LightEventsResponse = try await perform(URLRequest(url: url))
            guard response.items.contains(where: { $0.helpCardId == helpRequest.id.uuidString }) else {
                return helpRequest
            }

            var refreshed = helpRequest
            refreshed.status = .answered
            refreshed.answers.append(HumanAnswer(text: "皮皮已经根据来一句汇总出结果。", nickname: "皮皮", timeLabel: "刚刚"))
            return refreshed
        } catch {
            return helpRequest
        }
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        do {
            let response: V1HelpCardDetailEnvelope = try await perform(URLRequest(url: endpoint("/v1/help-cards/\(id.uuidString)")))
            return response.summary.model(fallbackTitle: "求一个")
        } catch {
            return nil
        }
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        do {
            var components = URLComponents(url: endpoint("/v1/help-feed"), resolvingAgainstBaseURL: false)!
            let queryItems = [
                URLQueryItem(name: "device_id", value: deviceUid),
                URLQueryItem(name: "limit", value: "10")
            ]
            components.queryItems = queryItems

            guard let url = components.url else { return [] }
            let response: V1HelpFeedResponse = try await perform(URLRequest(url: url))
            return response.items.map { $0.model(fallbackTitle: "求一个") }
        } catch {
            return []
        }
    }

    func answer(_ text: String, for helpRequest: HelpRequest) async -> HelpRequest {
        do {
            let response: V1HelpCardOneLinerResponse = try await perform(makeRequest(
                path: "/v1/help-cards/\(helpRequest.id.uuidString)/one-liner",
                method: "POST",
                body: V1HelpCardOneLinerRequest(text: text, deviceId: deviceUid)
            ))
            var updated = helpRequest
            updated.answers.append(HumanAnswer(id: response.answerId ?? UUID(), text: text, nickname: "路过的人", timeLabel: "刚刚"))
            updated.rewardLabel = response.reward?.label ?? updated.rewardLabel
            updated.answerCount += 1
            updated.status = response.isFinalReady ? .answered : .published
            return updated
        } catch {
            var fallback = helpRequest
            fallback.answers.append(HumanAnswer(text: text, nickname: "路过的人", timeLabel: "刚刚"))
            fallback.answerCount += 1
            fallback.status = .answered
            return fallback
        }
    }

    func acceptCard(id: UUID?) async -> Bool {
        guard let id else { return false }

        do {
            let _: V1CardAcceptResponse = try await perform(makeRequest(
                path: "/v1/cards/\(id.uuidString)/accept",
                method: "POST",
                body: V1CardAcceptRequest(metadata: ["source": "ios"])
            ))
            return true
        } catch {
            return false
        }
    }

    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool {
        guard let id else { return false }

        do {
            let _: V1CardFeedbackResponse = try await perform(makeRequest(
                path: "/v1/cards/\(id.uuidString)/\(action.endpointPath)",
                method: "POST",
                body: V1CardFeedbackRequest(
                    deviceId: deviceUid,
                    reason: reason,
                    tags: [reason],
                    metadata: ["source": "ios", "surface": "chat_card"]
                )
            ))
            return true
        } catch {
            return false
        }
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory] {
        []
    }

    private func makeRequest<Body: Encodable>(path: String, method: String, body: Body) throws -> URLRequest {
        var request = URLRequest(url: endpoint(path))
        request.httpMethod = method
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        var request = authorized(request)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200..<300).contains(httpResponse.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            if status == 401, await AuthAPIService().refreshIfPossible() {
                request = authorized(request)
                let (retryData, retryResponse) = try await URLSession.shared.data(for: request)
                if let retryHTTP = retryResponse as? HTTPURLResponse,
                   (200..<300).contains(retryHTTP.statusCode) {
                    return try JSONDecoder().decode(Response.self, from: retryData)
                }
            }
            let body = String(data: data, encoding: .utf8) ?? ""
            print("BackendRecommendationService HTTP \(status) for \(request.url?.absoluteString ?? "<nil>"): \(body)")
            throw BackendServiceError.httpStatus(status, body)
        }

        do {
            return try JSONDecoder().decode(Response.self, from: data)
        } catch {
            let body = String(data: data, encoding: .utf8) ?? ""
            print("BackendRecommendationService decode failed for \(request.url?.absoluteString ?? "<nil>"): \(error). Body: \(body)")
            throw BackendServiceError.decoding(String(describing: error), body)
        }
    }

    private func publishedFallback(_ helpRequest: HelpRequest) -> HelpRequest {
        var fallback = helpRequest
        fallback.status = .published
        return fallback
    }

    private func shouldRetryWithFreshConversation(after error: Error, sessionId: UUID?) -> Bool {
        guard sessionId != nil, let backendError = error as? BackendServiceError else { return false }

        switch backendError {
        case let .httpStatus(status, _):
            return status == 404 || status == 409 || status >= 500
        case .decoding:
            return false
        }
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let accessToken = AuthTokenStore.accessToken, !accessToken.isEmpty {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}

private enum BackendServiceError: LocalizedError {
    case httpStatus(Int, String)
    case decoding(String, String)

    var errorDescription: String? {
        switch self {
        case let .httpStatus(status, body):
            "HTTP \(status): \(body.prefix(160))"
        case let .decoding(message, body):
            "JSON decode failed: \(message). Body: \(body.prefix(160))"
        }
    }
}

struct AuthenticatedAccount: Equatable {
    let email: String?
    let displayName: String
}

struct AuthAPIService: Sendable {
    private let baseURL = AppAPIEnvironment.baseURL

    func requestCode(email: String) async throws {
        var request = URLRequest(url: endpoint("/v1/auth/request-code"))
        request.httpMethod = "POST"
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(V1AuthRequestCodeRequest(
            email: email,
            deviceId: DeviceIdentity.uid,
            platform: "ios",
            appVersion: "0.1.0"
        ))
        let _: V1AuthRequestCodeResponse = try await perform(request)
    }

    func verify(email: String, code: String) async throws -> AuthenticatedAccount {
        var request = URLRequest(url: endpoint("/v1/auth/verify-code"))
        request.httpMethod = "POST"
        request.timeoutInterval = 18
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(V1AuthVerifyCodeRequest(
            email: email,
            code: code,
            deviceId: DeviceIdentity.uid,
            platform: "ios",
            appVersion: "0.1.0"
        ))
        let response: V1AuthVerifyCodeResponse = try await perform(request)
        AuthTokenStore.accessToken = response.tokens.accessToken
        AuthTokenStore.refreshToken = response.tokens.refreshToken
        AuthTokenStore.email = response.user.email
        AuthTokenStore.displayName = response.user.displayName
        return AuthenticatedAccount(email: response.user.email, displayName: response.user.displayName)
    }

    func updateDisplayName(_ displayName: String) async throws -> AuthenticatedAccount {
        var request = URLRequest(url: endpoint("/v1/auth/me"))
        request.httpMethod = "PATCH"
        request.timeoutInterval = 12
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request = authorized(request)
        request.httpBody = try JSONEncoder().encode(V1AuthUpdateMeRequest(displayName: displayName))
        let response: V1AuthMeResponse = try await perform(request)
        AuthTokenStore.email = response.user.email
        AuthTokenStore.displayName = response.user.displayName
        return AuthenticatedAccount(email: response.user.email, displayName: response.user.displayName)
    }

    func refreshIfPossible() async -> Bool {
        guard let refreshToken = AuthTokenStore.refreshToken, !refreshToken.isEmpty else { return false }
        do {
            var request = URLRequest(url: endpoint("/v1/auth/refresh"))
            request.httpMethod = "POST"
            request.timeoutInterval = 12
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(V1AuthRefreshRequest(refreshToken: refreshToken))
            let response: V1AuthRefreshResponse = try await perform(request)
            AuthTokenStore.accessToken = response.tokens.accessToken
            AuthTokenStore.refreshToken = response.tokens.refreshToken
            return true
        } catch {
            AuthTokenStore.clear()
            return false
        }
    }

    func logout() async {
        guard let refreshToken = AuthTokenStore.refreshToken else {
            AuthTokenStore.clear()
            return
        }
        do {
            var request = URLRequest(url: endpoint("/v1/auth/logout"))
            request.httpMethod = "POST"
            request.timeoutInterval = 12
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(V1AuthRefreshRequest(refreshToken: refreshToken))
            let _: V1AuthLogoutResponse = try await perform(request)
        } catch {
            // Logout is best-effort on the client; local credentials must still go away.
        }
        AuthTokenStore.clear()
    }

    func deleteAccount() async throws {
        guard AuthTokenStore.accessToken?.isEmpty == false else {
            AuthTokenStore.clear()
            return
        }

        var request = URLRequest(url: endpoint("/v1/auth/me"))
        request.httpMethod = "DELETE"
        request.timeoutInterval = 12
        request = authorized(request)
        let _: V1AuthDeleteMeResponse = try await perform(request)
        AuthTokenStore.clear()
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BackendServiceError.httpStatus(status, body)
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let accessToken = AuthTokenStore.accessToken, !accessToken.isEmpty {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
}

struct UserLightEvent: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let body: String
    let createdAt: String?
}

struct UserDashboardSnapshot: Equatable, Sendable {
    let pendingReward: Int
    let grantedReward: Int
    let rejectedReward: Int
    let answeredCount: Int
    let qualityTier: String
    let answerStatusCounts: [String: Int]
    let rewardStatusCounts: [String: Int]
    let rewardItems: [RewardLedgerItem]
    let lightEvents: [UserLightEvent]

    static let empty = UserDashboardSnapshot(
        pendingReward: 0,
        grantedReward: 0,
        rejectedReward: 0,
        answeredCount: 0,
        qualityTier: "new",
        answerStatusCounts: [:],
        rewardStatusCounts: [:],
        rewardItems: [],
        lightEvents: []
    )
}

enum RewardLedgerStatus: String, Codable, Hashable, Sendable {
    case pending
    case granted
    case rejected

    init(rawStatus: String) {
        switch rawStatus {
        case "granted", "accepted":
            self = .granted
        case "rejected":
            self = .rejected
        default:
            self = .pending
        }
    }

    var label: String {
        switch self {
        case .pending:
            "待确认"
        case .granted:
            "已获得"
        case .rejected:
            "未采用"
        }
    }

    var icon: String {
        switch self {
        case .pending:
            "clock"
        case .granted:
            "checkmark.seal"
        case .rejected:
            "minus.circle"
        }
    }
}

struct RewardLedgerItem: Identifiable, Hashable, Sendable {
    let id: String
    let title: String
    let subtitle: String
    let valueLabel: String
    let status: RewardLedgerStatus
    let createdAt: String?
}

enum SubmittedAnswerStatus: String, Codable, Hashable, Sendable {
    case pending
    case accepted
    case rejected

    var label: String {
        switch self {
        case .pending:
            "待采纳"
        case .accepted:
            "已采纳"
        case .rejected:
            "未采用"
        }
    }
}

struct SubmittedAnswerRecord: Identifiable, Hashable, Sendable {
    let id: UUID
    let helpRequestId: UUID
    let questionTitle: String
    let questionContext: String
    let text: String
    let rewardLabel: String
    let status: SubmittedAnswerStatus
    let timeLabel: String

    init(
        id: UUID = UUID(),
        helpRequestId: UUID,
        questionTitle: String,
        questionContext: String,
        text: String,
        rewardLabel: String,
        status: SubmittedAnswerStatus = .pending,
        timeLabel: String = "刚刚"
    ) {
        self.id = id
        self.helpRequestId = helpRequestId
        self.questionTitle = questionTitle
        self.questionContext = questionContext
        self.text = text
        self.rewardLabel = rewardLabel
        self.status = status
        self.timeLabel = timeLabel
    }
}

struct ProfileAPIService: Sendable {
    private let baseURL = AppAPIEnvironment.baseURL
    private let deviceUid = DeviceIdentity.uid

    func fetchSnapshot() async -> UserDashboardSnapshot {
        let rewards = try? await fetchRewards()
        let quality = try? await fetchAnswererQuality()
        let lights = try? await fetchLightEvents()

        return UserDashboardSnapshot(
            pendingReward: rewards?.pendingValue ?? 0,
            grantedReward: rewards?.grantedValue ?? 0,
            rejectedReward: rewards?.rejectedValue ?? 0,
            answeredCount: quality?.answers.submittedCount ?? 0,
            qualityTier: quality?.quality.tier ?? "new",
            answerStatusCounts: quality?.answers.statusCounts ?? [:],
            rewardStatusCounts: quality?.rewards?.statusCounts ?? [:],
            rewardItems: (rewards?.items ?? []).map(\.ledgerItem),
            lightEvents: (lights?.items ?? []).map { item in
                UserLightEvent(
                    id: item.id,
                    title: item.title ?? "有新消息",
                    body: item.body ?? item.message ?? "皮皮有新进展。",
                    createdAt: item.createdAt
                )
            }
        )
    }

    private func fetchRewards() async throws -> V1ProfileRewardsResponse {
        var components = URLComponents(url: endpoint("/v1/rewards/me"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "device_uid", value: deviceUid)]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid rewards URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func fetchAnswererQuality() async throws -> V1ProfileAnswererQualityResponse {
        var components = URLComponents(url: endpoint("/v1/answerers/me/quality"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "device_uid", value: deviceUid)]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid quality URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func fetchLightEvents() async throws -> V1ProfileLightEventsResponse {
        var components = URLComponents(url: endpoint("/v1/light-events"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "device_uid", value: deviceUid),
            URLQueryItem(name: "limit", value: "10")
        ]
        guard let url = components.url else { throw BackendServiceError.decoding("invalid lights URL", "") }
        return try await perform(URLRequest(url: url))
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        var request = authorized(request)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? -1
            if status == 401, await AuthAPIService().refreshIfPossible() {
                request = authorized(request)
                let (retryData, retryResponse) = try await URLSession.shared.data(for: request)
                if let retryHTTP = retryResponse as? HTTPURLResponse, (200..<300).contains(retryHTTP.statusCode) {
                    return try JSONDecoder().decode(Response.self, from: retryData)
                }
            }
            let body = String(data: data, encoding: .utf8) ?? ""
            throw BackendServiceError.httpStatus(status, body)
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }

    private func authorized(_ request: URLRequest) -> URLRequest {
        var request = request
        if let token = AuthTokenStore.accessToken, !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }
}

private struct V1ProfileRewardsResponse: Decodable {
    let pendingValue: Int
    let grantedValue: Int
    let rejectedValue: Int
    let items: [V1ProfileRewardItem]

    enum CodingKeys: String, CodingKey {
        case pendingValue = "pending_value"
        case grantedValue = "granted_value"
        case rejectedValue = "rejected_value"
        case items
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pendingValue = try container.decodeIfPresent(Int.self, forKey: .pendingValue) ?? 0
        grantedValue = try container.decodeIfPresent(Int.self, forKey: .grantedValue) ?? 0
        rejectedValue = try container.decodeIfPresent(Int.self, forKey: .rejectedValue) ?? 0
        items = try container.decodeIfPresent([V1ProfileRewardItem].self, forKey: .items) ?? []
    }
}

private struct V1ProfileRewardItem: Decodable {
    let id: String
    let type: String?
    let label: String?
    let value: Int
    let status: String
    let helpCardId: String?
    let helpAnswerId: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case label
        case value
        case status
        case helpCardId = "help_card_id"
        case helpAnswerId = "help_answer_id"
        case createdAt = "created_at"
    }

    var ledgerItem: RewardLedgerItem {
        let normalizedStatus = RewardLedgerStatus(rawStatus: status)
        let rewardLabel = label?.isEmpty == false ? label! : "+\(value)"
        return RewardLedgerItem(
            id: helpCardId ?? helpAnswerId ?? id,
            title: "来一句奖励",
            subtitle: normalizedStatus == .pending ? "等待对方采纳" : "来自一次来一句回答",
            valueLabel: rewardLabel,
            status: normalizedStatus,
            createdAt: createdAt
        )
    }
}

private struct V1ProfileAnswererQualityResponse: Decodable {
    let quality: V1ProfileQuality
    let answers: V1ProfileAnswers
    let rewards: V1ProfileAnswerRewards?
}

private struct V1ProfileQuality: Decodable {
    let tier: String
}

private struct V1ProfileAnswers: Decodable {
    let submittedCount: Int
    let statusCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case submittedCount = "submitted_count"
        case statusCounts = "status_counts"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        submittedCount = try container.decodeIfPresent(Int.self, forKey: .submittedCount) ?? 0
        statusCounts = try container.decodeIfPresent([String: Int].self, forKey: .statusCounts) ?? [:]
    }
}

private struct V1ProfileAnswerRewards: Decodable {
    let pendingCount: Int
    let grantedCount: Int
    let rejectedCount: Int
    let statusCounts: [String: Int]

    enum CodingKeys: String, CodingKey {
        case pendingCount = "pending_count"
        case grantedCount = "granted_count"
        case rejectedCount = "rejected_count"
        case statusCounts = "status_counts"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        pendingCount = try container.decodeIfPresent(Int.self, forKey: .pendingCount) ?? 0
        grantedCount = try container.decodeIfPresent(Int.self, forKey: .grantedCount) ?? 0
        rejectedCount = try container.decodeIfPresent(Int.self, forKey: .rejectedCount) ?? 0
        statusCounts = try container.decodeIfPresent([String: Int].self, forKey: .statusCounts) ?? [
            "pending": pendingCount,
            "granted": grantedCount,
            "rejected": rejectedCount
        ]
    }
}

private struct V1ProfileLightEventsResponse: Decodable {
    let items: [V1ProfileLightEvent]
}

private struct V1ProfileLightEvent: Decodable {
    let id: String
    let title: String?
    let body: String?
    let message: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case body
        case message
        case createdAt = "created_at"
    }
}

private enum DeviceIdentity {
    static let uid: String = {
        let key = "just_pick_this_device_uid"
        if let existing = KeychainStore.string(for: key), !existing.isEmpty {
            return existing
        }
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            KeychainStore.set(existing, for: key)
            return existing
        }

        let generated = "ios-\(UUID().uuidString)"
        UserDefaults.standard.set(generated, forKey: key)
        KeychainStore.set(generated, for: key)
        return generated
    }()
}

enum AuthTokenStore {
    private static let accessKey = "auth_access_token"
    private static let refreshKey = "auth_refresh_token"
    private static let emailKey = "auth_email"
    private static let displayNameKey = "auth_display_name"

    static var accessToken: String? {
        get { KeychainStore.string(for: accessKey) }
        set { KeychainStore.setOrDelete(newValue, for: accessKey) }
    }

    static var refreshToken: String? {
        get { KeychainStore.string(for: refreshKey) }
        set { KeychainStore.setOrDelete(newValue, for: refreshKey) }
    }

    static var email: String? {
        get { KeychainStore.string(for: emailKey) }
        set { KeychainStore.setOrDelete(newValue, for: emailKey) }
    }

    static var displayName: String? {
        get { KeychainStore.string(for: displayNameKey) }
        set { KeychainStore.setOrDelete(newValue, for: displayNameKey) }
    }

    static func clear() {
        KeychainStore.delete(accessKey)
        KeychainStore.delete(refreshKey)
        KeychainStore.delete(emailKey)
        KeychainStore.delete(displayNameKey)
    }
}

private enum KeychainStore {
    private static let service = "com.justpickthis.pipii"

    static func string(for key: String) -> String? {
        var query = baseQuery(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func setOrDelete(_ value: String?, for key: String) {
        if let value, !value.isEmpty {
            set(value, for: key)
        } else {
            delete(key)
        }
    }

    static func set(_ value: String, for key: String) {
        let data = Data(value.utf8)
        var query = baseQuery(key)
        let attributes = [kSecValueData as String: data]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            query[kSecValueData as String] = data
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    static func delete(_ key: String) {
        SecItemDelete(baseQuery(key) as CFDictionary)
    }

    private static func baseQuery(_ key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
    }
}

private struct V1AuthRequestCodeRequest: Encodable {
    let email: String
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case email
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1AuthRequestCodeResponse: Decodable {
    let ok: Bool
}

private struct V1AuthVerifyCodeRequest: Encodable {
    let email: String
    let code: String
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case email
        case code
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1AuthVerifyCodeResponse: Decodable {
    let user: V1AuthUser
    let tokens: V1AuthTokens
}

private struct V1AuthRefreshRequest: Encodable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

private struct V1AuthUpdateMeRequest: Encodable {
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
    }
}

private struct V1AuthMeResponse: Decodable {
    let user: V1AuthUser
}

private struct V1AuthRefreshResponse: Decodable {
    let tokens: V1AuthTokens
}

private struct V1AuthLogoutResponse: Decodable {
    let ok: Bool
}

private struct V1AuthDeleteMeResponse: Decodable {
    let ok: Bool
    let deleted: Bool?
}

private struct V1AuthUser: Decodable {
    let id: String
    let email: String?
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case id
        case email
        case displayName = "display_name"
    }
}

private struct V1AuthTokens: Decodable {
    let accessToken: String
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
    }
}

private struct V1BootstrapRequest: Encodable {
    let deviceId: String
    let platform: String
    let appVersion: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case platform
        case appVersion = "app_version"
    }
}

private struct V1BootstrapResponse: Decodable {
    let conversationId: String

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
    }
}

private struct V1ChatTurnRequest: Encodable {
    let message: String
    let conversationId: String?
    let deviceId: String
    let clientContext: V1ClientContext
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case message
        case conversationId = "conversation_id"
        case deviceId = "device_id"
        case clientContext = "client_context"
        case metadata
    }
}

private struct V1ClientContext: Encodable {
    let source: String
    let location: V1ClientLocation?
    let decisionLocation: V1DecisionLocationContext?

    enum CodingKeys: String, CodingKey {
        case source
        case location
        case decisionLocation = "decision_location"
    }
}

struct V1ClientLocation: Encodable {
    let latitude: Double
    let longitude: Double
    let horizontalAccuracy: Double
    let capturedAt: String
    let provider: String
    let coordType: String

    enum CodingKeys: String, CodingKey {
        case latitude
        case longitude
        case horizontalAccuracy = "horizontal_accuracy"
        case capturedAt = "captured_at"
        case provider
        case coordType = "coord_type"
    }

    init(location: CLLocation) {
        self.latitude = location.coordinate.latitude
        self.longitude = location.coordinate.longitude
        self.horizontalAccuracy = max(location.horizontalAccuracy, 0)
        self.capturedAt = ISO8601DateFormatter().string(from: location.timestamp)
        self.provider = "ios_core_location"
        self.coordType = "ios_core_location"
    }

    init?(context: DecisionLocationContext) {
        guard let latitude = context.latitude, let longitude = context.longitude else {
            return nil
        }

        self.latitude = latitude
        self.longitude = longitude
        self.horizontalAccuracy = 0
        self.capturedAt = ISO8601DateFormatter().string(from: Date())
        self.provider = context.source == "current" ? "ios_core_location" : context.source
        self.coordType = context.source == "current" ? "ios_core_location" : "manual_hint"
    }
}

private struct V1DecisionLocationContext: Encodable {
    let label: String
    let city: String?
    let area: String?
    let latitude: Double?
    let longitude: Double?
    let source: String

    init(context: DecisionLocationContext) {
        self.label = context.label
        self.city = context.city
        self.area = context.area
        self.latitude = context.latitude
        self.longitude = context.longitude
        self.source = context.source
    }
}

@MainActor
final class DeviceLocationProvider: NSObject, @preconcurrency CLLocationManagerDelegate {
    static let shared = DeviceLocationProvider()

    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<V1ClientLocation?, Never>?
    private var timeoutTask: Task<Void, Never>?

    private override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
        manager.distanceFilter = 50
    }

    func currentLocationPayload() async -> V1ClientLocation? {
        guard CLLocationManager.locationServicesEnabled() else { return nil }

        return await withCheckedContinuation { continuation in
            finish(nil)
            self.continuation = continuation
            timeoutTask?.cancel()
            timeoutTask = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                await MainActor.run {
                    self?.finish(nil)
                }
            }

            switch manager.authorizationStatus {
            case .notDetermined:
                manager.requestWhenInUseAuthorization()
            case .authorizedAlways, .authorizedWhenInUse:
                manager.requestLocation()
            case .denied, .restricted:
                finish(nil)
            @unknown default:
                finish(nil)
            }
        }
    }

    func currentDecisionLocation() async -> DecisionLocationContext? {
        guard let payload = await currentLocationPayload() else { return nil }
        let location = CLLocation(latitude: payload.latitude, longitude: payload.longitude)
        let placemarks = try? await CLGeocoder().reverseGeocodeLocation(location)
        let placemark = placemarks?.first
        let city = placemark?.locality ?? placemark?.administrativeArea
        let area = placemark?.subLocality ?? placemark?.name
        let labelParts = [city, area]
            .compactMap { value in
                value?.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty }
        let label = labelParts.isEmpty ? "当前位置" : labelParts.joined(separator: " · ")

        return DecisionLocationContext(
            label: label,
            city: city,
            area: area,
            latitude: payload.latitude,
            longitude: payload.longitude,
            source: "current"
        )
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        switch manager.authorizationStatus {
        case .authorizedAlways, .authorizedWhenInUse:
            manager.requestLocation()
        case .denied, .restricted:
            finish(nil)
        case .notDetermined:
            break
        @unknown default:
            finish(nil)
        }
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else {
            finish(nil)
            return
        }
        finish(V1ClientLocation(location: location))
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        finish(nil)
    }

    private func finish(_ payload: V1ClientLocation?) {
        timeoutTask?.cancel()
        timeoutTask = nil
        continuation?.resume(returning: payload)
        continuation = nil
    }
}

private struct V1ChatTurnResponse: Decodable {
    let conversationId: String
    let userTurnId: String?
    let assistantMessage: String?
    let cards: [V1CardSummary]?
    let helpCards: [V1HelpCardSummary]?

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case userTurnId = "user_turn_id"
        case assistantMessage = "assistant_message"
        case cards
        case helpCards = "help_cards"
    }

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        if let card = cards?.first {
            decision = .top1(card.model(query: query))
        } else if let helpCard = helpCards?.first {
            decision = .ask(helpCard.model(fallbackTitle: query))
        } else {
            decision = .none
        }

        return RecommendationResult(
            sessionId: UUID(uuidString: conversationId),
            questionId: questionId,
            history: [],
            decision: decision,
            serviceNotice: notice
        )
    }

    private var notice: ServiceNotice? {
        guard cards?.isEmpty ?? true, helpCards?.isEmpty ?? true else { return nil }
        guard let assistantMessage else { return nil }
        let trimmed = assistantMessage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return ServiceNotice(title: "皮皮", detail: trimmed)
    }

    private var questionId: UUID? {
        if let questionId = cards?.first?.metadata?.questionId {
            return questionId
        }
        return helpCards?.first?.metadata?.questionId ?? UUID(uuidString: userTurnId ?? "")
    }
}

private struct V1CardSummary: Decodable {
    let id: UUID?
    let title: String
    let subtitle: String?
    let oneLiner: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?
    let status: String?
    let image: V1ImageAsset?
    let metadata: V1CardMetadata?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case subtitle
        case oneLiner = "one_liner"
        case bullets
        case warning
        case followups
        case status
        case image
        case metadata
    }

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedReason = clean(oneLiner, fallback: "我把已有线索收成一个选择。")
        let resolvedFollowups = removeAskHuman(
            from: cleanArrayAllowingEmpty(followups)
        )

        return TopPick(
            cardId: id,
            query: fallbackQuery,
            preface: "别查了,就这个。",
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: resolvedReason,
            bullets: cleanArrayAllowingEmpty(bullets),
            warning: clean(warning, fallback: ""),
            followups: resolvedFollowups,
            referenceImage: image?.model
        )
    }
}

private struct V1CardMetadata: Decodable {
    let questionId: UUID?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
    }
}

private struct V1ImageAsset: Decodable {
    let id: UUID?
    let url: String?
    let sourceUrl: String?
    let sourceDomain: String?
    let caption: String?
    let verified: Bool
    let isAiGenerated: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case url
        case sourceUrl = "source_url"
        case sourceDomain = "source_domain"
        case caption
        case verified
        case isAiGenerated = "is_ai_generated"
    }

    var model: ReferenceImage? {
        guard let url, verified, !isAiGenerated else { return nil }
        return ReferenceImage(
            url: url,
            sourceURL: sourceUrl,
            sourceDomain: sourceDomain,
            caption: caption,
            isAiGenerated: isAiGenerated
        )
    }
}

private struct V1HelpCardSummary: Decodable {
    let id: UUID?
    let title: String?
    let prompt: String
    let status: String?
    let contextText: String?
    let oneLiner: String?
    let reward: V1RewardPayload?
    let answerCount: Int?
    let card: V1CardSummary?
    let metadata: V1HelpCardMetadata?

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case prompt
        case status
        case contextText = "context_text"
        case oneLiner = "one_liner"
        case reward
        case answerCount = "answer_count"
        case card
        case metadata
    }

    func model(fallbackTitle: String) -> HelpRequest {
        var answers: [HumanAnswer] = []
        if let card {
            answers.append(HumanAnswer(text: clean(card.oneLiner, fallback: card.title), nickname: "皮皮", timeLabel: "刚刚"))
        }

        return HelpRequest(
            id: id ?? UUID(),
            title: clean(title, fallback: clean(prompt, fallback: fallbackTitle)),
            context: clean(contextText, fallback: clean(oneLiner, fallback: "这题不硬选 · 等懂的人来一句")),
            rewardLabel: reward?.label ?? "+10",
            answerCount: answerCount ?? metadata?.answerCount ?? answers.count,
            status: helpRequestStatus(from: status),
            answers: answers
        )
    }

    private func helpRequestStatus(from status: String?) -> HelpRequestStatus {
        switch status {
        case "draft":
            .draft
        case "published", "collecting", "open":
            .published
        case "final_ready", "answered":
            .answered
        case "closed", "completed":
            .completed
        default:
            .draft
        }
    }
}

private struct V1HelpCardDetailEnvelope: Decodable {
    let summary: V1HelpCardSummary

    enum CodingKeys: String, CodingKey {
        case helpCard = "help_card"
    }

    init(from decoder: Decoder) throws {
        let container = try? decoder.container(keyedBy: CodingKeys.self)
        if let summary = try container?.decodeIfPresent(V1HelpCardSummary.self, forKey: .helpCard) {
            self.summary = summary
        } else {
            self.summary = try V1HelpCardSummary(from: decoder)
        }
    }
}

private struct V1RewardPayload: Decodable {
    let label: String?
    let value: Int?
    let status: String?
}

private struct V1HelpCardMetadata: Decodable {
    let questionId: UUID?
    let answerCount: Int?
    let minAnswersRequired: Int?

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
        case answerCount = "answer_count"
        case minAnswersRequired = "min_answers_required"
    }
}

private struct V1HelpFeedResponse: Decodable {
    let items: [V1HelpCardSummary]
}

private struct V1HelpCardOneLinerRequest: Encodable {
    let text: String
    let deviceId: String

    enum CodingKeys: String, CodingKey {
        case text
        case deviceId = "device_id"
    }
}

private struct V1HelpCardOneLinerResponse: Decodable {
    let helpCardId: String
    let answerId: UUID?
    let reward: V1RewardPayload?
    let toast: String?
    let shouldAdvance: Bool?
    let metadata: V1OneLinerMetadata?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
        case answerId = "answer_id"
        case reward
        case toast
        case shouldAdvance = "should_advance"
        case metadata
    }

    var isFinalReady: Bool {
        metadata?.finalizationReady == true
    }
}

private struct V1OneLinerMetadata: Decodable {
    let finalizationReady: Bool?

    enum CodingKeys: String, CodingKey {
        case finalizationReady = "finalization_ready"
    }
}

private struct V1LightEventsResponse: Decodable {
    let items: [V1LightEvent]
}

private struct V1LightEvent: Decodable {
    let helpCardId: String?

    enum CodingKeys: String, CodingKey {
        case helpCardId = "help_card_id"
    }
}

private struct V1CardAcceptRequest: Encodable {
    let metadata: [String: String]
}

private struct V1CardFeedbackRequest: Encodable {
    let deviceId: String
    let reason: String
    let tags: [String]
    let metadata: [String: String]

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case reason
        case tags
        case metadata
    }
}

private struct V1CardAcceptResponse: Decodable {
    let cardId: String
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case cardId = "card_id"
        case accepted
    }
}

private struct V1CardFeedbackResponse: Decodable {
    let cardId: String
    let accepted: Bool

    enum CodingKeys: String, CodingKey {
        case cardId = "card_id"
        case accepted
    }
}

struct MockCloudRecommendationService: RecommendationService {
    func submit(query: String, sessionId: UUID?, locationContext: DecisionLocationContext?) async -> RecommendationResult {
        try? await Task.sleep(for: .milliseconds(650))

        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if shouldAskHuman(for: trimmed) {
            return RecommendationResult(
                sessionId: sessionId ?? UUID(),
                questionId: UUID(),
                history: [],
                decision: .ask(MockData.helpRequest(for: trimmed)),
                serviceNotice: nil
            )
        }

        return RecommendationResult(
            sessionId: sessionId ?? UUID(),
            questionId: UUID(),
            history: [],
            decision: .top1(MockData.topPick(for: trimmed)),
            serviceNotice: nil
        )
    }

    func publish(_ request: HelpRequest, sessionId: UUID?, questionId: UUID?) async -> HelpRequest {
        var updated = request
        updated.status = .published
        return updated
    }

    func refresh(_ request: HelpRequest) async -> HelpRequest {
        request
    }

    func fetchHelpRequest(id: UUID) async -> HelpRequest? {
        nil
    }

    func answerQueue(excluding sessionId: UUID?) async -> [HelpRequest] {
        [MockData.defaultHelpRequest]
    }

    func answer(_ text: String, for request: HelpRequest) async -> HelpRequest {
        var updated = request
        updated.answers.append(HumanAnswer(text: text, nickname: "路过的人", timeLabel: "刚刚"))
        updated.answerCount += 1
        updated.status = .answered
        return updated
    }

    func acceptCard(id: UUID?) async -> Bool {
        true
    }

    func sendCardFeedback(id: UUID?, action: CardFeedbackAction, reason: String) async -> Bool {
        id != nil && !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func complete(sessionId: UUID?, questionId: UUID?, helpRequestId: UUID?, source: String) async -> [QuestionHistory] {
        []
    }

    private func shouldAskHuman(for query: String) -> Bool {
        let uncertainKeywords = ["韩国", "首尔", "明洞", "小众", "求一个", "真人", "不敢", "失败", "没结果", "no result", "fail"]
        return uncertainKeywords.contains { keyword in
            query.localizedCaseInsensitiveContains(keyword)
        }
    }
}

private struct RecommendationRequest: Encodable {
    let query: String
    let sessionId: String?
}

private struct HelpRequestPayload: Encodable {
    let id: String
    let sessionId: String?
    let questionId: String?
    let title: String
    let context: String
    let status: HelpRequestStatus
    let answers: [HumanAnswerPayload]

    init(helpRequest: HelpRequest, status: HelpRequestStatus, sessionId: UUID?, questionId: UUID?) {
        self.id = helpRequest.id.uuidString
        self.sessionId = sessionId?.uuidString
        self.questionId = questionId?.uuidString
        self.title = helpRequest.title
        self.context = helpRequest.context
        self.status = status
        self.answers = helpRequest.answers.map(HumanAnswerPayload.init)
    }
}

private struct HumanAnswerPayload: Encodable {
    let id: String
    let text: String
    let nickname: String
    let timeLabel: String

    init(answer: HumanAnswer) {
        self.id = answer.id.uuidString
        self.text = answer.text
        self.nickname = answer.nickname
        self.timeLabel = answer.timeLabel
    }
}

private struct AnswerPayload: Encodable {
    let text: String
    let nickname: String
}

private struct CompleteQuestionPayload: Encodable {
    let helpRequestId: String?
    let source: String
}

private struct SessionEnvelope: Decodable {
    let session: SessionResponse
}

private struct SessionResponse: Decodable {
    let questions: [QuestionHistoryResponse]
}

private struct RecommendationResponse: Decodable {
    let sessionId: UUID?
    let questionId: UUID?
    let history: [QuestionHistoryResponse]?
    let kind: String
    let topPick: TopPickResponse?
    let helpRequest: HelpRequestResponse?

    func result(for query: String) -> RecommendationResult {
        let decision: RecommendationDecision
        switch kind {
        case "top1":
            guard let topPick else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .top1(topPick.model(query: query))
        case "ask":
            guard let helpRequest else {
                decision = .ask(MockData.backendFallbackHelpRequest(for: query))
                break
            }
            decision = .ask(helpRequest.model(fallbackTitle: query))
        default:
            decision = .none
        }

        return RecommendationResult(
            sessionId: sessionId,
            questionId: questionId,
            history: history?.compactMap(\.model) ?? [],
            decision: decision,
            serviceNotice: nil
        )
    }
}

private struct QuestionHistoryResponse: Decodable {
    let id: UUID?
    let query: String?
    let status: String?
    let helpRequestId: UUID?
    let topPick: TopPickResponse?

    var model: QuestionHistory? {
        guard let id, let query, let status else { return nil }
        return QuestionHistory(
            id: id,
            query: query,
            status: status,
            helpRequestId: helpRequestId,
            topPick: topPick?.model(query: query)
        )
    }
}

private struct HelpRequestEnvelope: Decodable {
    let helpRequest: HelpRequestResponse
}

private struct HelpRequestListEnvelope: Decodable {
    let helpRequests: [HelpRequestResponse]
}

private struct TopPickResponse: Decodable {
    let query: String?
    let preface: String?
    let title: String?
    let subtitle: String?
    let reason: String?
    let bullets: [String]?
    let warning: String?
    let followups: [String]?

    func model(query fallbackQuery: String) -> TopPick {
        let resolvedFollowups = removeAskHuman(
            from: cleanArray(followups, fallback: ["为什么?", "换个小众的"])
        )

        return TopPick(
            cardId: nil,
            query: clean(query, fallback: fallbackQuery),
            preface: clean(preface, fallback: "别查了,就这个。"),
            title: clean(title, fallback: "先选一个最稳的"),
            subtitle: clean(subtitle, fallback: "不用再比较。"),
            reason: clean(reason, fallback: "你已经给了位置和目的,这题先做一个低后悔选择。"),
            bullets: cleanArray(bullets, fallback: MockData.genericTopPick(for: fallbackQuery).bullets),
            warning: clean(warning, fallback: "如果你明确不喜欢这个类型,就别选。"),
            followups: resolvedFollowups.isEmpty ? ["为什么?", "换个小众的"] : resolvedFollowups,
            referenceImage: nil
        )
    }
}

private struct HelpRequestResponse: Decodable {
    let id: UUID?
    let title: String?
    let context: String?
    let status: HelpRequestStatus?
    let answers: [HumanAnswerResponse]?

    func model(fallbackTitle: String) -> HelpRequest {
        HelpRequest(
            id: id ?? UUID(),
            title: clean(title, fallback: fallbackTitle),
            context: clean(context, fallback: "这题不硬选 · 等懂的人来一句"),
            status: status ?? .draft,
            answers: answers?.map(\.model) ?? []
        )
    }
}

private struct HumanAnswerResponse: Decodable {
    let id: UUID?
    let text: String?
    let nickname: String?
    let timeLabel: String?

    var model: HumanAnswer {
        HumanAnswer(
            id: id ?? UUID(),
            text: clean(text, fallback: ""),
            nickname: clean(nickname, fallback: "路过的人"),
            timeLabel: clean(timeLabel, fallback: "刚刚")
        )
    }
}

@MainActor
@Observable
final class AppSession {
    private(set) var sessionId: UUID?
    private(set) var currentQuestionId: UUID?
    private(set) var currentQuery = ""
    private(set) var currentTopPick: TopPick?
    private(set) var currentHelpRequest: HelpRequest?
    private(set) var history: [QuestionHistory] = []
    private(set) var favoriteChoices: [QuestionHistory] = []
    private(set) var hiddenFavoriteChoiceIds: Set<UUID> = []
    private(set) var submittedAnswers: [SubmittedAnswerRecord] = []
    private(set) var answerQueue: [HelpRequest] = []
    private(set) var answerTarget: HelpRequest?
    private(set) var submitState: SubmitState = .idle
    private(set) var serviceNotice: ServiceNotice?

    @ObservationIgnored private let service: any RecommendationService
    @ObservationIgnored private let documentationDemo: String?

    init(service: any RecommendationService, documentationDemo: String? = nil) {
        self.service = service
        self.documentationDemo = documentationDemo

        #if DEBUG
        applyDocumentationDemo(documentationDemo)
        #endif
    }

    var isSubmitting: Bool {
        submitState == .loading
    }

    var topPick: TopPick {
        currentTopPick ?? MockData.genericTopPick(for: currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery)
    }

    var helpRequest: HelpRequest {
        currentHelpRequest ?? MockData.defaultHelpRequest
    }

    var answerRequest: HelpRequest? {
        answerTarget ?? answerQueue.first
    }

    var nextAnswerRequest: HelpRequest? {
        guard let current = answerRequest else { return nil }
        return answerQueue.first { $0.id != current.id }
    }

    func startNewConversation() {
        sessionId = nil
        currentQuestionId = nil
        currentQuery = ""
        currentTopPick = nil
        currentHelpRequest = nil
        serviceNotice = nil
        submitState = .idle
    }

    func submit(query: String, locationContext: DecisionLocationContext? = nil) async -> RecommendationDecision {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        currentQuery = trimmed
        submitState = .loading

        let result = await service.submit(query: trimmed, sessionId: sessionId, locationContext: locationContext)
        serviceNotice = result.serviceNotice
        sessionId = result.sessionId ?? sessionId
        currentQuestionId = result.questionId ?? currentQuestionId
        if !result.history.isEmpty {
            history = result.history
        } else if !result.decision.isEmpty {
            upsertLocalHistory(
                query: trimmed,
                status: status(for: result.decision),
                helpRequestId: helpRequestId(for: result.decision),
                topPick: topPick(for: result.decision)
            )
        }
        apply(result.decision)
        submitState = .idle
        return result.decision
    }

    func restoreHistoryItem(_ item: QuestionHistory) async -> HistoryDestination {
        currentQuestionId = item.id
        currentQuery = item.query

        if shouldOpenHelpRequest(for: item) {
            currentTopPick = nil
            if let helpRequestId = item.helpRequestId,
               let request = await service.fetchHelpRequest(id: helpRequestId) {
                currentHelpRequest = request
            } else {
                currentHelpRequest = fallbackHelpRequest(for: item)
            }
            return .ask
        }

        currentHelpRequest = nil
        currentTopPick = item.topPick ?? MockData.genericTopPick(for: item.query)
        return .result
    }

    func helpRequestDetail(for item: QuestionHistory) async -> HelpRequest {
        if currentHelpRequest?.id == item.helpRequestId {
            return currentHelpRequest ?? fallbackHelpRequest(for: item)
        }

        if let helpRequestId = item.helpRequestId,
           let request = await service.fetchHelpRequest(id: helpRequestId) {
            return mergedLocalHelpAnswers(into: request, historyItem: item)
        }

        return fallbackHelpRequest(for: item)
    }

    func makeHelpRequestFromCurrentTopPick() {
        let query = currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery
        let pick = topPick
        Task {
            _ = await service.sendCardFeedback(id: pick.cardId, action: .askHuman, reason: "想听真人意见")
        }
        currentHelpRequest = HelpRequest(
            title: query,
            context: "已经给过一个选择: \(pick.title) · 还想听懂的人来一句",
            status: .draft,
            answers: []
        )
    }

    func addHelpContext(_ text: String) {
        let supplement = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !supplement.isEmpty else { return }

        ensureHelpRequest()
        currentHelpRequest?.context += "\n补充: \(supplement)"
    }

    func publishCurrentRequest() async {
        ensureHelpRequest()
        guard let request = currentHelpRequest else { return }
        let published = await service.publish(request, sessionId: sessionId, questionId: currentQuestionId)
        currentHelpRequest = published
        upsertLocalHistory(query: published.title, status: "waiting_for_human", helpRequestId: published.id, topPick: currentTopPick)
    }

    func refreshCurrentHelpRequest() async -> Bool {
        guard let request = currentHelpRequest else { return false }
        let previousAnswerCount = request.answers.count
        let refreshed = await service.refresh(request)
        currentHelpRequest = refreshed
        if refreshed.answers.count > previousAnswerCount {
            upsertLocalHistory(query: refreshed.title, status: "answer_received", helpRequestId: refreshed.id, topPick: currentTopPick)
            return true
        }
        return false
    }

    func loadAnswerQueue() async {
        #if DEBUG
        if documentationDemo == "answer", !answerQueue.isEmpty {
            answerTarget = answerQueue.first
            return
        }
        #endif

        let requests = await service.answerQueue(excluding: sessionId)
        answerQueue = requests
        answerTarget = requests.first
    }

    func addAnswer(_ text: String) async {
        let answer = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !answer.isEmpty else { return }

        guard let request = answerRequest else { return }
        let updated = await service.answer(answer, for: request)
        let record = SubmittedAnswerRecord(
            helpRequestId: request.id,
            questionTitle: request.title,
            questionContext: request.context,
            text: answer,
            rewardLabel: updated.rewardLabel.isEmpty ? request.rewardLabel : updated.rewardLabel
        )
        submittedAnswers.removeAll { $0.helpRequestId == request.id }
        submittedAnswers.insert(record, at: 0)

        if currentHelpRequest?.id == updated.id {
            currentHelpRequest = updated
        }
        answerQueue.removeAll { $0.id == request.id }
        answerTarget = answerQueue.first
    }

    func advanceAnswerRequest() {
        guard let request = answerRequest else { return }
        answerQueue.removeAll { $0.id == request.id }
        answerTarget = answerQueue.first
    }

    func acceptCurrentTopPick() async {
        let accepted = await service.acceptCard(id: currentTopPick?.cardId)
        let remoteHistory: [QuestionHistory]
        if accepted {
            remoteHistory = []
        } else {
            remoteHistory = await service.complete(
                sessionId: sessionId,
                questionId: currentQuestionId,
                helpRequestId: nil,
                source: "top1"
            )
        }
        markCurrentQuestionCompleted(remoteHistory: remoteHistory)
        currentTopPick = nil
        currentQuery = ""
    }

    func saveCurrentTopPickToFavorites() {
        let query = currentQuery.isEmpty ? topPick.query : currentQuery
        let item = QuestionHistory(
            id: currentQuestionId ?? UUID(),
            query: query.isEmpty ? MockData.queryPlaceholder : query,
            status: "saved",
            helpRequestId: nil,
            topPick: currentTopPick ?? topPick
        )
        favoriteChoices.removeAll { $0.id == item.id }
        hiddenFavoriteChoiceIds.remove(item.id)
        favoriteChoices.insert(item, at: 0)
    }

    func removeFavoriteChoice(id: UUID) {
        favoriteChoices.removeAll { $0.id == id }
        hiddenFavoriteChoiceIds.insert(id)
    }

    @discardableResult
    func sendCurrentTopPickFeedback(action: CardFeedbackAction, reason: String) async -> Bool {
        await service.sendCardFeedback(id: currentTopPick?.cardId, action: action, reason: reason)
    }

    func acceptCurrentHelpAnswer() async {
        let remoteHistory = await service.complete(
            sessionId: sessionId,
            questionId: currentQuestionId,
            helpRequestId: currentHelpRequest?.id,
            source: "human_answer"
        )
        markCurrentQuestionCompleted(remoteHistory: remoteHistory)
        currentHelpRequest = nil
        currentQuery = ""
    }

    private func apply(_ decision: RecommendationDecision) {
        switch decision {
        case .none:
            currentTopPick = nil
            currentHelpRequest = nil
        case .top1(let pick):
            currentTopPick = pick
            currentHelpRequest = nil
        case .ask(let request):
            currentTopPick = nil
            currentHelpRequest = request
        }
    }

    private func ensureHelpRequest() {
        guard currentHelpRequest == nil else { return }
        currentHelpRequest = MockData.helpRequest(for: currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery)
    }

    private func upsertLocalHistory(query: String, status: String, helpRequestId: UUID?, topPick: TopPick?) {
        if let currentQuestionId,
           let index = history.firstIndex(where: { $0.id == currentQuestionId }) {
            let existing = history[index]
            history[index] = QuestionHistory(
                id: currentQuestionId,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick ?? existing.topPick
            )
            return
        }

        let id = currentQuestionId ?? UUID()
        currentQuestionId = id
        history.insert(
            QuestionHistory(
                id: id,
                query: query,
                status: status,
                helpRequestId: helpRequestId,
                topPick: topPick
            ),
            at: 0
        )
    }

    private func status(for decision: RecommendationDecision) -> String {
        switch decision {
        case .none:
            "completed"
        case .top1:
            "top1"
        case .ask:
            "waiting_for_human"
        }
    }

    private func helpRequestId(for decision: RecommendationDecision) -> UUID? {
        switch decision {
        case .none:
            nil
        case .top1:
            nil
        case .ask(let request):
            request.id
        }
    }

    private func topPick(for decision: RecommendationDecision) -> TopPick? {
        switch decision {
        case .none:
            nil
        case .top1(let pick):
            pick
        case .ask:
            nil
        }
    }

    private func shouldOpenHelpRequest(for item: QuestionHistory) -> Bool {
        if item.helpRequestId != nil {
            return true
        }

        return item.status == "waiting_for_human" || item.status == "answer_received"
    }

    private func fallbackHelpRequest(for item: QuestionHistory) -> HelpRequest {
        let request = HelpRequest(
            id: item.helpRequestId ?? UUID(),
            title: item.query,
            context: item.status == "completed"
                ? "这题已经完成。"
                : "这题不硬选 · 等懂的人来一句",
            status: helpRequestStatus(for: item),
            answers: []
        )
        return mergedLocalHelpAnswers(into: request, historyItem: item)
    }

    private func mergedLocalHelpAnswers(into request: HelpRequest, historyItem: QuestionHistory) -> HelpRequest {
        var merged = request
        let localAnswers = submittedAnswers
            .filter { $0.helpRequestId == historyItem.helpRequestId || $0.helpRequestId == request.id }
            .map { answer in
                HumanAnswer(
                    id: answer.id,
                    text: answer.text,
                    nickname: "我",
                    timeLabel: answer.timeLabel
                )
            }
        for answer in localAnswers where !merged.answers.contains(where: { $0.id == answer.id || $0.text == answer.text }) {
            merged.answers.append(answer)
        }
        merged.answerCount = max(merged.answerCount, merged.answers.count)
        return merged
    }

    private func helpRequestStatus(for item: QuestionHistory) -> HelpRequestStatus {
        switch item.status {
        case "completed":
            .completed
        case "answer_received":
            .answered
        case "waiting_for_human":
            .published
        default:
            .draft
        }
    }

    private func markCurrentQuestionCompleted(remoteHistory: [QuestionHistory]) {
        if !remoteHistory.isEmpty {
            history = remoteHistory
            return
        }

        let query = currentQuery.isEmpty ? MockData.queryPlaceholder : currentQuery
        upsertLocalHistory(query: query, status: "completed", helpRequestId: currentHelpRequest?.id, topPick: currentTopPick)
    }

    #if DEBUG
    private func applyDocumentationDemo(_ demo: String?) {
        guard let demo else { return }

        switch demo {
        case "result":
            currentQuery = MockData.demoQuery
            currentTopPick = MockData.topPick(for: MockData.demoQuery)
        case "ask":
            currentQuery = "在韩国逛街，不想去明洞"
            currentHelpRequest = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞。先收集懂的人一句建议。",
                status: .draft,
                answers: []
            )
        case "answer":
            let request = HelpRequest(
                title: "在韩国逛街，不想去明洞",
                context: "用户说：在韩国逛街，不想去明洞，想小众，求一个。",
                status: .published,
                answers: []
            )
            answerQueue = [request]
            answerTarget = request
        default:
            break
        }
    }
    #endif
}

enum MockData {
    static let queryPlaceholder = "我在哪,想干什么?"
    static let demoQuery = "我现在在大同喜晋道,不知道吃什么"
    static func backendUnavailableNotice(error _: Error) -> ServiceNotice {
        ServiceNotice(
            title: "皮皮",
            detail: "这轮没连上服务，原话我先留着。你可以重试，或者改一句再发。"
        )
    }

    static let defaultHelpRequest = HelpRequest(
        title: "这题先求一个",
        context: "我先帮你发出去，等懂的人来一句。"
    )

    static func genericTopPick(for query: String) -> TopPick {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? queryPlaceholder : query

        return TopPick(
            cardId: nil,
            query: resolvedQuery,
            preface: "先别纠结。",
            title: "等一个更稳的选择",
            subtitle: "这题我不硬选。",
            reason: "现在还不够确定，先收一句真人建议更稳。",
            bullets: [
                "不硬凑推荐。",
                "先等更多线索。",
                "等有人补一句再给最终答案。"
            ],
            warning: "如果你已经有明确偏好，可以直接补一句。",
            followups: ["补一句偏好", "问真人"],
            referenceImage: nil
        )
    }

    static func topPick(for query: String) -> TopPick {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? Self.demoQuery : query

        return TopPick(
            cardId: nil,
            query: resolvedQuery,
            preface: "别查了,就这个。",
            title: "刀削面 + 肉丸子",
            subtitle: "第一次来大同,就吃这个最稳。",
            reason: "你已经给了位置和目的,这题不需要再比较菜单。先吃一个地方感强、点偏概率低的组合。",
            bullets: [
                "你已经到店了,别再研究菜单。",
                "第一次来大同,要吃一个地方感强、不容易点偏的。",
                "这组比只点面更完整。"
            ],
            warning: "不爱吃面,就别选。",
            followups: ["为什么?", "换个小众的"],
            referenceImage: nil
        )
    }

    static func helpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        if resolvedQuery.localizedCaseInsensitiveContains("韩国")
            || resolvedQuery.localizedCaseInsensitiveContains("首尔")
            || resolvedQuery.localizedCaseInsensitiveContains("明洞") {
            return defaultHelpRequest
        }

        return HelpRequest(
            title: resolvedQuery,
            context: "这题不硬选 · 等懂的人来一句"
        )
    }

    static func backendFallbackHelpRequest(for query: String) -> HelpRequest {
        let resolvedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? defaultHelpRequest.title : query

        return HelpRequest(
            title: resolvedQuery,
            context: "现在还不够确定 · 发出去等懂的人来一句"
        )
    }
}

private func clean(_ value: String?, fallback: String) -> String {
    guard let value else { return fallback }
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty ? fallback : trimmed
}

private func cleanArray(_ value: [String]?, fallback: [String]) -> [String] {
    guard let value else { return fallback }
    let cleaned = value
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
    return cleaned.isEmpty ? fallback : cleaned
}

private func cleanArrayAllowingEmpty(_ value: [String]?) -> [String] {
    guard let value else { return [] }
    return value
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        .filter { !$0.isEmpty }
}

private func removeAskHuman(from values: [String]) -> [String] {
    values.filter { !$0.localizedCaseInsensitiveContains("问真人") }
}
